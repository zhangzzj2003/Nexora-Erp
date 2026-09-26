"""由选定的 Nexus + Aurora 标志生成桌面安装包图标。"""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
SOURCE = RESOURCES / "nexora-nexus-aurora-logo.png"


def make_icon() -> Image.Image:
    with Image.open(SOURCE) as source:
        logo = source.convert("RGBA")

    # 生成图边缘有极低透明度的散点；清除后按可见内容裁切，保证小尺寸图标清晰。
    alpha = logo.getchannel("A").point(lambda value: 0 if value < 16 else value)
    logo.putalpha(alpha)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("标志图片没有可见内容")
    logo = logo.crop(bounds)

    # 四周留白，确保 macOS Dock、Windows 桌面和托盘中都不会贴边。
    logo.thumbnail((800, 800), Image.Resampling.LANCZOS)
    icon = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    icon.alpha_composite(logo, ((1024 - logo.width) // 2, (1024 - logo.height) // 2))
    return icon


def main() -> None:
    RESOURCES.mkdir(exist_ok=True)
    icon = make_icon()
    icon.save(RESOURCES / "icon.png")
    icon.resize((64, 64), Image.Resampling.LANCZOS).save(RESOURCES / "tray.png")
    icon.save(RESOURCES / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # Pillow 直接写 ICNS，避免依赖不同 macOS 版本的 iconutil 校验行为。
    icon.save(RESOURCES / "icon.icns", format="ICNS")


if __name__ == "__main__":
    main()
