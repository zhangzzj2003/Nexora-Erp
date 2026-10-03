# 报价 PDF 中文字体

`NotoSansSC-Regular.ttf` 由 [Google Fonts 的 Noto Sans SC 可变字体](https://github.com/google/fonts/blob/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf) 固定为 `wght=400` 生成，用于在 PDF 中嵌入中文字符。该字体按同目录的 [SIL OFL 1.1 授权文件](OFL.txt) 分发。服务运行时不依赖 `fontTools` 或操作系统字体。

PyInstaller 构建须把本目录复制到服务程序的 `app/sales/fonts/`，使源码运行和安装版都能从 `crm_quote_pdf.py` 相邻路径读取字体。字体不属于数据库或业务单据附件。
