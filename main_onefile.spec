# -*- mode: python ; coding: utf-8 -*-
# main_onefile.spec —— 发票整理工具-SXL 单文件打包配置

from PyInstaller.utils.hooks import collect_all

# ===================== 资源与元数据 =====================
datas = [('logo.ico', '.'), ('models', 'models')]
# ★ 如果有 splash.png，取消下一行注释，启用启动画面
# datas.append(('splash.png', '.'))

binaries = []

hiddenimports = [
    'fitz', 'pymupdf', 'imghdr', 'cv2', 'lmdb',
    'scipy.io', 'scipy.special', 'scipy.ndimage',
    'skimage', 'skimage.io', 'skimage.color',
    'tools', 'tools.infer',
    'tools.infer.predict_det',
    'tools.infer.predict_rec',
    'tools.infer.predict_cls',
    'tools.infer.predict_system',
    'ppocr', 'ppocr.utils', 'ppocr.utils.utility',
    'ppocr.data', 'ppocr.postprocess',
]

collect_pkgs = [
    'paddle', 'paddleocr', 'paddlex', 'pdfplumber', 'pdfminer',
    'pymupdf', 'pyclipper', 'shapely', 'imgaug', 'imageio',
    'scipy', 'skimage', 'lmdb', 'cv2',
]

for pkg in collect_pkgs:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print('[spec] collect_all OK -> ' + pkg)
    except Exception as e:
        print('[spec] collect_all SKIP -> ' + pkg + ': ' + str(e))

copy_metadata_list = [
    'imageio', 'imgaug', 'paddleocr', 'paddlepaddle',
    'shapely', 'pyclipper', 'scikit-image',
    'opencv-python-headless', 'numpy', 'scipy', 'lmdb',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2'],
    noarchive=False,
    copy_metadata=copy_metadata_list,
)

pyz = PYZ(a.pure)

# ===================== 启动画面（可选） =====================
# ★ 如果有 splash.png，取消下面整段注释
# splash = Splash(
#     'splash.png',
#     binaries=a.binaries,
#     datas=a.datas,
#     always_on_top=True,
# )

# ===================== onefile EXE =====================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,           # 二进制打进 exe
    a.datas,              # 资源打进 exe
    # splash,             # ★ 有 splash 时取消注释
    # splash.binaries,    # ★ 有 splash 时取消注释
    exclude_binaries=False,
    name='发票整理工具-单文件',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.ico',
)