import sys
import os

# ============================================================================
# ★ 修复 1：必须放在所有 import 之前 —— 分离本进程控制台 + 隐藏残留窗口
# ============================================================================
if sys.platform == "win32":
    import ctypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _k32.FreeConsole()
    except Exception:
        pass
    try:
        _hwnd = _k32.GetConsoleWindow()
        if _hwnd:
            ctypes.WinDLL("user32", use_last_error=True).ShowWindow(_hwnd, 0)  # SW_HIDE
    except Exception:
        pass

# ============================================================================
# ★ 修复 2：拦截所有子进程创建 —— Paddle 初始化时的子进程探测才是真正的"黑框一闪"
# ============================================================================
import subprocess
if sys.platform == "win32":
    _orig_popen_init = subprocess.Popen.__init__

    def _silent_popen_init(self, *args, **kwargs):
        if kwargs.get("startupinfo") is None:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x08000000
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _silent_popen_init

    _orig_system = os.system
    def _silent_system(cmd):
        return _orig_system(f'cmd /c "{cmd}" >nul 2>&1')
    os.system = _silent_system

# ============================================================================
# ★ 修复 3：Paddle 相关环境变量 —— 必须在所有 paddle 导入前
# ============================================================================
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['GLOG_minloglevel'] = '3'
os.environ['GLOG_logtostderr'] = '0'
os.environ['GLOG_v'] = '0'
os.environ['GLOG_log_dir'] = ''
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.environ['FLAGS_call_stack_level'] = '0'
os.environ['FLAGS_eager_delete_tensor_gb'] = '0'

# ============================================================================
# 普通 import
# ============================================================================
import re
import shutil
import threading
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLineEdit, QLabel, QPlainTextEdit, QFileDialog,
                               QMessageBox, QCheckBox)
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtGui import QIcon
from PySide6 import QtWidgets, QtCore, QtGui
from collections import defaultdict
import warnings

warnings.filterwarnings("ignore")

# ===================== 单文件 EXE 环境适配 =====================
if getattr(sys, 'frozen', False):
    _base = Path(sys._MEIPASS)
    for _sub in [r'paddle\libs', r'paddle\base', r'_internal\paddle\libs']:
        _p = _base / _sub
        if _p.is_dir():
            os.environ['PATH'] = str(_p) + os.pathsep + os.environ.get('PATH', '')
# ==============================================================

# ===================== 配置区 =====================
def get_resource_path():
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).parent

BASE_DIR = get_resource_path()
LOGO_PATH = str(BASE_DIR / "logo.ico")
OUTPUT_FOLDER_NAME = "单据重命名输出"
COMPANY_KEYWORDS = ["有限公司", "有限责任公司", "集团", "股份公司", "分公司", "事务所"]
NOISE_WORDS = {"国", "制", "全", "章", "局", "税", "务", "内", "蒙", "古"}
MAX_FILENAME_LEN = 200

APP_AUTHOR = "SXL"
APP_VERSION = "v26.9.19"
# =====================================================================

# ============================================================================
# ★ 修复 4：兜底工具 —— 每次 OCR 加载完成后再次清理可能冒出来的 console
# ============================================================================
def _kill_console_again():
    if sys.platform != "win32":
        return
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            ctypes.WinDLL("user32", use_last_error=True).ShowWindow(hwnd, 0)
    except Exception:
        pass

# ===================== OCR 单例（懒加载 + 线程安全） =====================
_OCR_INSTANCE = None
_OCR_LOCK = threading.Lock()

def get_ocr():
    """全局复用一个 PaddleOCR 实例，优先用本地 models 目录，否则回退默认路径"""
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        with _OCR_LOCK:
            if _OCR_INSTANCE is None:
                from paddleocr import PaddleOCR

                if getattr(sys, 'frozen', False):
                    model_root = Path(sys._MEIPASS) / "models"
                else:
                    model_root = Path(__file__).parent / "models"

                det_dir = model_root / "det" / "ch" / "ch_PP-OCRv4_det_infer"
                rec_dir = model_root / "rec" / "ch" / "ch_PP-OCRv4_rec_infer"
                cls_dir = model_root / "cls" / "ch_ppocr_mobile_v2.0_cls_infer"

                if det_dir.exists() and rec_dir.exists():
                    _OCR_INSTANCE = PaddleOCR(
                        lang="ch",
                        use_angle_cls=False,
                        use_gpu=False,
                        det_model_dir=str(det_dir),
                        rec_model_dir=str(rec_dir),
                        cls_model_dir=str(cls_dir) if cls_dir.exists() else None,
                        show_log=False,
                    )
                else:
                    # 无本地模型：回退到默认路径（首次联网下载）
                    _OCR_INSTANCE = PaddleOCR(
                        lang="ch",
                        use_textline_orientation=False,
                        use_gpu=False,
                        show_log=False,
                    )
                _kill_console_again()
    return _OCR_INSTANCE
# =====================================================================

# ===================== 工具函数 =====================
def format_date(raw_date: str) -> str:
    pat = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", raw_date)
    if pat:
        y = pat.group(1)
        m = pat.group(2).zfill(2)
        d = pat.group(3).zfill(2)
        return f"{y}{m}{d}"
    return raw_date

def clean_raw_text(text: str) -> str:
    text = text.replace("|", " ")
    return text

def extract_pdf_text(pdf_path: str, ocr) -> tuple:
    import pdfplumber
    import pymupdf as fitz

    text = ""
    source = "pdfplumber"
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        text = ""

    text = clean_raw_text(text)
    is_air_ticket = "航空运输电子客票行程单" in text
    miss_key_info = "旅客姓名" not in text

    if len(text.strip()) > 20 and not (is_air_ticket and miss_key_info):
        return text, source

    source = "ocr"
    all_text = []
    try:
        doc = fitz.open(pdf_path)
        try:
            for page in doc:
                pix = page.get_pixmap()
                img_bytes = pix.tobytes("png")
                result = ocr.ocr(img_bytes)
                for res in result:
                    if not res:
                        continue
                    for line in res:
                        try:
                            txt = line[1][0].strip()
                            if txt:
                                all_text.append(txt)
                        except (IndexError, TypeError):
                            continue
        finally:
            doc.close()
        text = "\n".join(all_text)
        text = clean_raw_text(text)
    except Exception:
        return "", source
    return text, source

def detect_doc_type(text: str):
    if "航空运输电子客票行程单" in text:
        return "飞机票"
    if "12306" in text or "限乘" in text or "铁路电子客票" in text or "统铁" in text:
        return "火车票"
    if "发票号码" in text:
        if "住宿费" in text or "住宿服务" in text:
            return "住宿票"
        elif "*电信服务*" in text:
            return "电话费"
        else:
            return "发票"
    else:
        return "未知单据"

def extract_invoice_item_name(text):
    pat = re.search(r"\*[^*]+\*([^\s\n，。；]+)", text)
    if pat:
        item = pat.group(1).strip()
        if 2 <= len(item) <= 30:
            return item
    return None

def parse_info_by_type(text: str, doc_type: str):
    info = {
        "单据类型": doc_type, "发票项目": "", "代码": "", "号码": "",
        "姓名": "", "出发地": "", "目的地": "", "日期": "", "金额": "",
        "不含税金额": "", "销售方名称": "", "帐期": "", "手机号": ""
    }

    if doc_type in ["发票", "住宿票", "电话费"]:
        if doc_type == "发票":
            item_name = extract_invoice_item_name(text)
            if item_name:
                info["发票项目"] = item_name

        code_match = re.search(r"发票代码[:：]?\s*(\d{12})", text)
        num_match = re.search(r"发票号码[:：]?\s*(\d+)", text)
        date_match = re.search(r"开票日期[:：]?\s*(\d{4}年\d{1,2}月\d{1,2}日)", text)
        amt_total_match = re.search(r"价税合计.*?[¥￥](\d+\.\d{2})", text)
        amt_no_tax_match = re.search(r"合\s*计\s*[¥￥](\d+\.\d{2})", text)
        buyer_match = re.search(r"购买方名称[:：]?\s*([^\n]+)", text)

        seller_name = ""
        sn_short = re.search(r"销\s+名称[:：]?\s*([^\n]+)", text)
        if sn_short:
            seller_name = sn_short.group(1).strip()
        else:
            sell_block_match = re.search(r"销售方(.*?)(?=购买方|备\s*注|$)", text, re.DOTALL)
            if sell_block_match:
                sn_match = re.search(r"名称[:：]?\s*([^\n]+)", sell_block_match.group(1))
                if sn_match:
                    seller_name = sn_match.group(1).strip()
        info["销售方名称"] = seller_name

        if code_match:
            info["代码"] = code_match.group(1).strip()
        if num_match:
            info["号码"] = num_match.group(1).strip()
        if date_match:
            info["日期"] = date_match.group(1).strip()
        if amt_total_match:
            info["金额"] = amt_total_match.group(1).strip()
        elif amt_no_tax_match:
            info["金额"] = amt_no_tax_match.group(1).strip()
        if buyer_match:
            buyer_name = buyer_match.group(1).strip()
            if not any(k in buyer_name for k in COMPANY_KEYWORDS):
                info["姓名"] = buyer_name[:20]

        if doc_type == "电话费":
            period_match = re.search(r"[帐账]\s*期[:：]\s*(\d{6})", text)
            if period_match:
                info["帐期"] = period_match.group(1).strip()

            phone_all = re.findall(r"\d{11}", text)
            inv_no = info["号码"]
            for p_candidate in phone_all:
                if p_candidate != inv_no and p_candidate.startswith("1"):
                    info["手机号"] = p_candidate
                    break

    elif doc_type == "火车票":
        name_match = re.search(r"姓名[:：]?\s*([\u4e00-\u9fa5]{2,4})"
                               r"|\d+\*{4}\d+\s+([\u4e00-\u9fa5]{2,4})", text)
        if name_match:
            for g in name_match.groups():
                if g is not None:
                    info["姓名"] = g.strip()
                    break

        travel_date_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)\s*\d{1,2}:\d{1,2}\s*开", text)
        date_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", text)
        if travel_date_match:
            info["日期"] = travel_date_match.group(1).strip()
        elif date_match:
            info["日期"] = date_match.group(1).strip()

        amt_match = re.search(r"[¥￥](\d+\.?\d*)", text)
        if amt_match:
            info["金额"] = amt_match.group(1)

        train_match = re.search(r"([\u4e00-\u9fa5]{2,8})\s+[GDCZTK]\d+\s+([\u4e00-\u9fa5]{2,8})", text)
        if train_match:
            s1 = train_match.group(1).strip()
            s2 = train_match.group(2).strip()
            if not any(ch in NOISE_WORDS for ch in s1):
                info["出发地"] = s1
            if not any(ch in NOISE_WORDS for ch in s2):
                info["目的地"] = s2
        else:
            train_match2 = re.search(r"([\u4e00-\u9fa5]{2,8})\s+([\u4e00-\u9fa5]{2,8})\s+[GDCZTK]\d+", text)
            if train_match2:
                s1 = train_match2.group(1).strip()
                s2 = train_match2.group(2).strip()
                if not any(ch in NOISE_WORDS for ch in s1):
                    info["出发地"] = s1
                if not any(ch in NOISE_WORDS for ch in s2):
                    info["目的地"] = s2

    elif doc_type == "飞机票":
        name_match = re.search(r"旅客姓名[:：]?\s*([\u4e00-\u9fa5]{2,4})(?![\u4e00-\u9fa5])"
                               r"|旅客姓名\s*\n\s*([\u4e00-\u9fa5]{2,4})"
                               r"|旅客姓名.*?\n\s*([\u4e00-\u9fa5]{2,4})", text)
        if name_match:
            for g in name_match.groups():
                if g is not None:
                    info["姓名"] = g.strip()
                    break

        dep_match = re.search(r"自[:：]?\s*([^\n]+?)[\s\t]+", text)
        arr_match = re.search(r"至[:：]?\s*([^\n]+?)[\s\t]+", text)
        date_match = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", text)

        cny_list = re.findall(r"CNY\s*(\d+\.\d{2})", text)
        max_val = 0.0
        for s in cny_list:
            try:
                num = float(s)
                if num > max_val:
                    max_val = num
            except ValueError:
                continue
        if max_val > 0:
            info["金额"] = f"{max_val:.2f}"

        if dep_match:
            info["出发地"] = dep_match.group(1).strip()
        if arr_match:
            info["目的地"] = arr_match.group(1).strip()
        if date_match:
            info["日期"] = date_match.group(1).strip()

    return info

def safe_val(s: str) -> str:
    if not s or s.strip() == "":
        return "无"
    return s.strip()

def safe_filename(name: str) -> str:
    name = name.replace("\n", "").replace("\r", "").replace("\t", "")
    bad_chars = r'\/:*?"<>|'
    for c in bad_chars:
        name = name.replace(c, "_")
    stem, ext = os.path.splitext(name)
    stem = stem[:MAX_FILENAME_LEN - len(ext) - 10]
    return stem + ext

def build_output_filename(item):
    doc_type = item["单据类型"]
    invoice_item = safe_val(item.get("发票项目", ""))
    seller_name = safe_val(item["销售方名称"])
    fmt_date = format_date(item["日期"])
    amount = safe_val(item["金额"])

    if doc_type == "发票":
        base = invoice_item if invoice_item != "无" else "发票"
        fn = f"{base}-{seller_name}-{fmt_date}-{amount}.pdf"
    elif doc_type == "住宿票":
        fn = f"住宿费-{seller_name}-{fmt_date}-{amount}.pdf"
    elif doc_type == "电话费":
        period = safe_val(item["帐期"])
        phone = safe_val(item["手机号"])
        fn = f"电话费-{period}-{phone}-{amount}.pdf"
    elif doc_type == "火车票":
        fn = f"火车票-{safe_val(item['姓名'])}-{safe_val(item['出发地'])}-{safe_val(item['目的地'])}-{fmt_date}-{amount}.pdf"
    elif doc_type == "飞机票":
        fn = f"飞机票-{safe_val(item['姓名'])}-{safe_val(item['出发地'])}-{safe_val(item['目的地'])}-{fmt_date}-{amount}.pdf"
    else:
        return None
    return safe_filename(fn)

def generate_html_report(all_data_list, out_html_path, success_cnt, total_cnt, fail_cnt, other_copy_cnt):
    group_by_orig_date = defaultdict(list)
    for item in all_data_list:
        orig_date = safe_val(item.get("日期", ""))
        group_by_orig_date[orig_date].append(item)

    valid_items = [it for it in all_data_list
                   if it.get("单据类型", "") not in ["未知单据", "识别失败"]]

    total_money = 0.0
    for it in valid_items:
        try:
            total_money += float(safe_val(it.get("金额", "")))
        except Exception:
            pass
    total_money_text = f"￥{total_money:.2f}"

    group_html_parts = ["<h2>📆按日期分组</h2>"]
    for orig_date in sorted(group_by_orig_date.keys()):
        group_html_parts.append(f"<div class='date-title'>{orig_date}</div>")
        for it in group_by_orig_date[orig_date]:
            fname = build_output_filename(it)
            if fname is None:
                fname = it["_raw_name"]
            money = safe_val(it.get("金额", ""))
            money_text = f"￥{money}" if money != "无" else ""
            file_url = fname.replace("\\", "/")
            group_html_parts.append(f"""
    <div class="file-line">
         <a class="fname" href="{file_url}" target="_blank">{fname}</a>
         <span class="money">{money_text}</span>
      </div>
      <div class="file-divider"></div>
""")
    group_section = "\n".join(group_html_parts)

    sorted_all = sorted(valid_items, key=lambda x: format_date(x.get("日期", "")))
    detail_rows = []
    for idx, it in enumerate(sorted_all):
        disp_doc_type = safe_val(it.get("单据类型", ""))
        inv_item = safe_val(it.get("发票项目", ""))
        if disp_doc_type == "发票" and inv_item != "无":
            disp_doc_type = inv_item

        detail_rows.append((
            f"<tr data-sort-date='{format_date(it.get('日期', ''))}'>"
            f"<td>{idx+1}</td>"
            f"<td>{disp_doc_type}</td>"
            f"<td>{safe_val(it.get('日期', ''))}</td>"
            f"<td>{safe_val(it.get('姓名', ''))}</td>"
            f"<td>{safe_val(it.get('出发地', ''))}</td>"
            f"<td>{safe_val(it.get('目的地', ''))}</td>"
            f"<td>{safe_val(it.get('销售方名称', ''))}</td>"
            f"<td>{safe_val(it.get('金额', ''))}</td>"
            f"</tr>"
        ))

    detail_section = (
        '<hr><div class="toolbar">'
        '<h2>📋有效单据明细</h2>'
        '<div class="sort-btns">'
        '<button onclick="sortTable(\'date\')" id="btn-date">按日期排序 ↑</button>'
        '</div>'
        '</div>'
        '<div class="detail-wrap"><table id="detailTable" border="1" cellpadding="8" cellspacing="0">'
        "<tr style='background:#f0f0f0;'>"
        "<th>#</th><th>单据类型</th><th>发票日期</th><th>姓名</th><th>出发地</th><th>目的地</th><th>销售方名称</th><th>金额</th></tr>"
        + "\n".join(detail_rows) +
        "</table></div>"
    )

    full_html = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>单据统计报表</title>
<style>
*{box-sizing:border-box;}
body{font-family:"Microsoft YaHei",SimHei,Arial;font-size:14px;margin:24px;background:#ffffff;color:#333;}
.container{max-width:1200px;margin:0 auto;}

.header{
    background:linear-gradient(135deg,#407bff,#2b57bc);
    color:white;
    padding:18px 24px;
    border-radius:10px;
    margin-bottom:20px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    flex-wrap:wrap;
}
.header h1{margin:0 0 4px 0;font-size:20px;}
.header-desc{opacity:0.85;font-size:12px;}

.stat-block{
    display:flex;
    gap:16px;
    align-items:center;
}
.stat-item{
    text-align:center;
    padding:0 12px;
    border-left:1px solid rgba(255,255,255,0.3);
}
.stat-item:first-child{border-left:none;}
.stat-num{font-size:20px;font-weight:bold;}
.stat-label{font-size:11px;opacity:0.8;margin-top:2px;}

.date-title{
    font-size:16px;
    font-weight:bold;
    margin-top:16px;
    margin-bottom:8px;
}
.file-line{
    display:flex;
    justify-content:space-between;
    align-items:center;
    padding:6px 12px;
}
.fname{
    font-family:Consolas,"Microsoft YaHei";
    color:#1a73e8;
    text-decoration:none;
}
.fname:hover{
    text-decoration:underline;
}
.money{
    font-weight:bold;
    color:#c00;
}
.file-divider{
    height:1px;
    background-color:#e5e5e5;
    margin:0 12px;
}

hr{margin:30px 0;border:1px solid #cccccc;}
.toolbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:8px;}
.toolbar h2{margin:0;font-size:17px;}
.sort-btns button{border:1px solid #ccd6e0;background:#fff;padding:5px 12px;border-radius:5px;font-size:12px;cursor:pointer;}
.sort-btns button.active{background:#407bff;color:white;border-color:#407bff;}

.detail-wrap{overflow-x:auto;}
table{border-collapse:collapse;width:100%;}
th{background-color:#f2f2f2;text-align:left;padding:8px 10px;border:1px solid #bbb;}
td{padding:8px 10px;border:1px solid #bbb;}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div>
            <h1>统计报表</h1>
            <div class="header-desc">发票整理工具-SXL</div>
        </div>
        <div class="stat-block">
            <div class="stat-item">
                <div class="stat-num">''' + str(total_cnt) + '''</div>
                <div class="stat-label">总文件</div>
            </div>
            <div class="stat-item">
                <div class="stat-num">''' + str(success_cnt) + '''</div>
                <div class="stat-label">成功识别</div>
            </div>
            <div class="stat-item">
                <div class="stat-num">''' + str(fail_cnt) + '''</div>
                <div class="stat-label">无法识别PDF</div>
            </div>
            <div class="stat-item">
                <div class="stat-num">''' + str(other_copy_cnt) + '''</div>
                <div class="stat-label">其他类型复制</div>
            </div>
            <div class="stat-item">
                <div class="stat-num">''' + total_money_text + '''</div>
                <div class="stat-label">有效单据总金额</div>
            </div>
        </div>
    </div>
  ''' + group_section + detail_section + '''
    </div>
    <script>
let sortDirDate = "asc";
function sortTable(mode){
    const table = document.getElementById("detailTable");
    const tbody = table.tBodies[0];
    let rows = Array.from(tbody.querySelectorAll("tr"));
    if(mode === "date"){
        rows.sort((a,b)=>{
            const da = a.dataset.sortDate;
            const db = b.dataset.sortDate;
            if(sortDirDate === "asc"){
                return da.localeCompare(db);
            }else{
                return db.localeCompare(da);
            }
        });
        sortDirDate = sortDirDate === "asc" ? "desc":"asc";
        const btn = document.getElementById("btn-date");
        btn.innerText = sortDirDate==="asc"?"按日期排序 ↑":"按日期排序 ↓";
        tbody.innerHTML = "";
        rows.forEach(r=>tbody.appendChild(r));
    }
}
document.getElementById("btn-date").classList.add("active");
    </script>
</body>
</html>
'''
    with open(out_html_path, "w", encoding="utf-8") as f:
        f.write(full_html)

# ===================== OCR 预加载线程 =====================
class OcrPreloader(QThread):
    done_signal = Signal(bool)

    def run(self):
        try:
            get_ocr()
            _kill_console_again()
            self.done_signal.emit(True)
        except Exception:
            self.done_signal.emit(False)

# ===================== 后台处理线程 =====================
class WorkerThread(QThread):
    log_signal = Signal(str)
    finished_signal = Signal(bool, list, int, int, int, int, str)

    def __init__(self, folder_path, show_raw_text: bool):
        super().__init__()
        self.folder_path = folder_path
        self.show_raw_text = show_raw_text

    def run(self):
        try:
            self.log_signal.emit("正在准备PaddleOCR模型...")
            ocr = get_ocr()
            self.log_signal.emit("OCR模型就绪！开始扫描文件\n")

            p = Path(self.folder_path)
            out_dir = p / OUTPUT_FOLDER_NAME
            out_dir.mkdir(exist_ok=True)

            all_files = [f for f in p.glob("*") if f.is_file()]
            total_cnt = len(all_files)
            self.log_signal.emit(f"一共找到 {total_cnt} 个文件\n输出目录：{str(out_dir)}\n")
            excel_data = []
            fail_count = 0
            other_copy_count = 0
            success_count = 0

            for file_item in all_files:
                file_path = str(file_item)
                self.log_signal.emit(f"==== 处理文件：{file_item.name} ====")

                new_name = None
                info = None
                if file_item.suffix.lower() == ".pdf":
                    try:
                        text, src = extract_pdf_text(file_path, ocr)
                        self.log_signal.emit(f"文本来源：{src}")
                        if self.show_raw_text:
                            self.log_signal.emit(f"【原始文本】\n{text[:1000]}\n")
                        doc_type = detect_doc_type(text)
                        info = parse_info_by_type(text, doc_type)
                        if self.show_raw_text:
                            self.log_signal.emit(f"识别结果：{info}")
                        new_name = build_output_filename(info)

                        if new_name is not None:
                            success_count += 1
                        else:
                            fail_count += 1
                    except Exception as e:
                        self.log_signal.emit(f"⚠️ PDF识别失败：{str(e)}，原样复制")
                        info = {"单据类型": "识别失败", "_raw_name": file_item.name}
                        new_name = None
                        fail_count += 1

                    if new_name is None:
                        new_name = file_item.name
                        info["_raw_name"] = new_name
                    else:
                        new_name = safe_filename(new_name)
                    excel_data.append(info)
                else:
                    new_name = safe_filename(file_item.name)
                    self.log_signal.emit("非PDF文件，直接原样复制")
                    other_copy_count += 1

                new_path = out_dir / new_name
                idx = 1
                while new_path.exists():
                    stem = Path(new_name).stem
                    suffix = Path(new_name).suffix
                    new_path = out_dir / f"{stem}_{idx}{suffix}"
                    idx += 1
                shutil.copy2(file_item, new_path)
                self.log_signal.emit(f"复制到输出目录 -> {new_path.name}\n")

            self.log_signal.emit("✅ 文件复制与识别全部完成，请点击【查看报表】输出统计页面\n")
            self.finished_signal.emit(True, excel_data, total_cnt, success_count,
                                      fail_count, other_copy_count, "处理成功")
        except Exception as e:
            import traceback
            err_info = traceback.format_exc()
            self.log_signal.emit(f"❌ 全局异常：{str(e)}\n{err_info}")
            self.finished_signal.emit(False, [], 0, 0, 0, 0, str(e))

# ===================== UI窗口 =====================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("发票整理工具-SXL")
        self.resize(880, 740)

        ico_file = Path(LOGO_PATH)
        if ico_file.exists():
            self.setWindowIcon(QIcon(str(ico_file)))

        self.worker = None
        self.preloader = None
        self._mem_data = None
        self._mem_total = 0
        self._mem_success = 0
        self._mem_fail = 0
        self._mem_other = 0

        self.init_ui()

        # ==================== 状态栏：左侧状态 + 右侧制作人/版本 ====================
        self.statusBar().setStyleSheet("""
            QStatusBar{padding:0px;min-height:22px;max-height:22px;}
            QStatusBar::item{border:none;margin-top:-2px;}
        """)

        author_label = QtWidgets.QLabel(f"制作人：{APP_AUTHOR}")
        author_label.setStyleSheet("color: #666; padding-right: 6px;")
        self.statusBar().addPermanentWidget(author_label)

        sep = QtWidgets.QLabel("|")
        sep.setStyleSheet("color: #ccc;")
        self.statusBar().addPermanentWidget(sep)

        ver_label = QtWidgets.QLabel(f"版本：{APP_VERSION}")
        ver_label.setStyleSheet("color: #666; padding-left: 6px;")
        self.statusBar().addPermanentWidget(ver_label)
        # ============================================================

        self._start_ocr_preload()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        h_layout1 = QHBoxLayout()
        self.label_path = QLabel("目标文件夹：")
        self.edit_path = QLineEdit()
        self.edit_path.setPlaceholderText("点击【选择文件夹】指定存放PDF的目录")
        self.btn_select = QPushButton("选择文件夹")
        self.btn_select.setMinimumHeight(32)
        self.btn_select.clicked.connect(self.select_folder)
        h_layout1.addWidget(self.label_path)
        h_layout1.addWidget(self.edit_path)
        h_layout1.addWidget(self.btn_select)
        layout.addLayout(h_layout1)

        h_layout2 = QHBoxLayout()
        self.chk_show_raw = QCheckBox("显示原始日志")
        self.chk_show_raw.setChecked(False)
        self.btn_del_out = QPushButton("清空输出目录")
        self.btn_del_out.setMinimumHeight(32)
        self.btn_del_out.clicked.connect(self.delete_output_folder)

        self.btn_start = QPushButton("开始执行")
        self.btn_start.setMinimumHeight(32)
        self.btn_html = QPushButton("查看报表")
        self.btn_html.setMinimumHeight(32)
        self.btn_open_out = QPushButton("输出目录")
        self.btn_open_out.setMinimumHeight(32)

        h_layout2.addWidget(self.chk_show_raw)
        h_layout2.addSpacing(8)
        h_layout2.addWidget(self.btn_del_out)
        h_layout2.addStretch(1)
        h_layout2.addWidget(self.btn_start)
        h_layout2.addSpacing(8)
        h_layout2.addWidget(self.btn_html)
        h_layout2.addSpacing(8)
        h_layout2.addWidget(self.btn_open_out)
        layout.addLayout(h_layout2)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("运行日志输出在这里……")
        layout.addWidget(self.log_text)

        # 状态栏左侧标签
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label, 1)

        self.btn_open_out.clicked.connect(self.open_output_folder)
        self.btn_html.clicked.connect(self.on_gen_html)
        self.btn_start.clicked.connect(self.start_process)

    def _start_ocr_preload(self):
        self.log_text.appendPlainText("⏳ 正在后台预加载OCR模型，稍后点击【开始执行】将直接进入处理…")
        self.preloader = OcrPreloader()
        self.preloader.done_signal.connect(self._on_preload_done)
        self.preloader.start()

    def _on_preload_done(self, ok: bool):
        if ok:
            self.log_text.appendPlainText("✅ OCR模型预加载完成，可以开始执行\n")
        else:
            self.log_text.appendPlainText("⚠️ OCR模型预加载失败，执行时会自动重试\n")

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择PDF单据文件夹")
        if folder:
            self.edit_path.setText(folder)

    def open_output_folder(self):
        src_folder = self.edit_path.text().strip()
        if not src_folder or not os.path.isdir(src_folder):
            QMessageBox.warning(self, "提示", "请先选择源PDF文件夹！")
            return
        out_dir = Path(src_folder) / OUTPUT_FOLDER_NAME
        out_dir.mkdir(exist_ok=True)
        os.startfile(str(out_dir))

    def delete_output_folder(self):
        src_folder = self.edit_path.text().strip()
        if not src_folder or not os.path.isdir(src_folder):
            QMessageBox.warning(self, "提示", "请先选择源PDF文件夹！")
            return
        out_dir = Path(src_folder) / OUTPUT_FOLDER_NAME
        if not out_dir.exists():
            QMessageBox.information(self, "提示", "输出目录不存在，无需删除！")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除【{str(out_dir)}】文件夹及里面全部文件吗？\n删除后文件无法恢复！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                shutil.rmtree(out_dir)
                self.log_text.appendPlainText(f"✅ 已删除输出文件夹：{str(out_dir)}")
                QMessageBox.information(self, "完成", "输出目录删除成功！")
            except Exception as e:
                err_msg = f"删除失败：{str(e)}"
                self.log_text.appendPlainText(f"❌ {err_msg}")
                QMessageBox.critical(self, "错误", err_msg)

    def start_process(self):
        folder = self.edit_path.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "提示", "请先选择有效的文件夹！")
            return
        self.log_text.clear()
        self.status_label.setText("状态：正在扫描文件...")

        self.btn_start.setEnabled(False)
        self.btn_html.setEnabled(False)
        self.btn_open_out.setEnabled(False)
        self.btn_del_out.setEnabled(False)
        self._mem_data = None
        self.log_text.appendPlainText("===== 启动任务 =====")
        show_raw_flag = self.chk_show_raw.isChecked()
        self.worker = WorkerThread(folder, show_raw_text=show_raw_flag)
        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def append_log(self, msg):
        self.log_text.appendPlainText(msg)

    def on_finished(self, success, data_list, total_cnt, success_cnt,
                    fail_cnt, other_copy_cnt, msg):
        self.btn_start.setEnabled(True)
        self.btn_open_out.setEnabled(True)
        self.btn_del_out.setEnabled(True)
        if success:
            self._mem_data = data_list
            self._mem_total = total_cnt
            self._mem_success = success_cnt
            self._mem_fail = fail_cnt
            self._mem_other = other_copy_cnt
            self.status_label.setText(
                f"状态：处理完成 | 总文件：{total_cnt} | 成功识别：{success_cnt} | 无法识别PDF：{fail_cnt} | 其他类型复制：{other_copy_cnt}"
            )
            self.btn_html.setEnabled(True)
            QMessageBox.information(self, "完成", "任务执行完成！\n点击【查看报表】显示详情！")
        else:
            self.status_label.setText("状态：处理异常")
            self.btn_html.setEnabled(False)
            QMessageBox.critical(self, "失败", f"处理异常：{msg}")

    def on_gen_html(self):
        if self._mem_data is None or len(self._mem_data) == 0:
            QMessageBox.warning(self, "提示", "请先执行【开始执行】，得到单据数据后再生成报表！")
            return
        src_folder = self.edit_path.text().strip()
        out_dir = Path(src_folder) / OUTPUT_FOLDER_NAME
        out_dir.mkdir(exist_ok=True)
        html_path = out_dir / "单据统计报表.html"
        try:
            generate_html_report(self._mem_data, str(html_path),
                                 self._mem_success, self._mem_total,
                                 self._mem_fail, self._mem_other)
            self.log_text.appendPlainText(f"✅ HTML报表已生成：{html_path}")
            os.startfile(str(html_path))
        except Exception as e:
            import traceback
            self.log_text.appendPlainText(f"❌ HTML生成失败 {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"生成HTML异常：{str(e)}")

    def closeEvent(self, event):
        """关闭前等待后台线程，避免 QThread: Destroyed while thread is still running 警告"""
        if getattr(self, 'preloader', None) is not None and self.preloader.isRunning():
            self.preloader.wait(15000)

        if getattr(self, 'worker', None) is not None and self.worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "正在处理文件，确定要退出吗？\n退出后当前任务会中断。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
            self.worker.wait(3000)

        event.accept()

# ===================== 程序入口 =====================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    win.raise_()
    win.activateWindow()
    sys.exit(app.exec())