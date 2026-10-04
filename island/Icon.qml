// One icon language for the whole island: lucide strokes from island/icons (JD.glyphs),
// with the desktop's own icon theme left for the things the theme owns — app icons.
//
// Растр просят крупнее, чем показывают. Значок в доке вырастает под курсором в полтора раза, и
// растр, нарисованный по его обычному размеру, в этот момент расплывается: увеличивается уже
// картинка, а не значок. renderSize — во сколько раз просить крупнее; лишняя память тут копеечная,
// а мыло видно всем.
import QtQuick
import QtQuick.Effects
import Quickshell

Item {
    id: ic
    property string name: ""
    property string fallback: "system-run"
    property real implicitSize: 18
    property real renderSize: implicitSize * 2
    property color tint: JD.text1
    // Значок самой программы, а не наш штриховой. Для списка программ важно именно это: у нас есть
    // «app-window», и без этого признака все приложения выглядели одинаковым окошком, потому что
    // запасное имя application-x-executable само есть в нашем наборе и перебивало настоящий значок.
    property bool theme: false
    // Dock/tray: load icons synchronously so the first paint is not a blank slot.
    property bool syncLoad: false
    // Значок темы — только в главном потоке. Асинхронный Image уводит его в поток чтения картинок,
    // а KIconLoader не потокобезопасен: док грузит свои синхронно, и на старте два потока сходились
    // в нём — островок падал с SIGSEGV в KIconLoader::loadScaledIcon через раз. Файлы с диска
    // KIconLoader не трогают и грузятся в фоне, как раньше.
    readonly property bool loadAsync: !syncLoad && fileIcon && !String(resolvedName).startsWith("image:")
    // iOS-like wash over theme/file icons: original | light | clear | tinted | mono
    // (auto is tray-only; dock treats auto as original).
    // light/clear = frosted-glass lift (keep hue); tinted = coloured glass; mono = grey.
    // Never full-desaturate for "light" — that looked like broken B&W icons.
    property string iconPalette: "original"
    property color iconPaletteTint: "#7AC8FF"
    readonly property string _pal: {
        const w = String(iconPalette || "original").trim().toLowerCase()
        if (w === "auto") return "original"
        return ["original", "light", "clear", "tinted", "mono"].indexOf(w) >= 0 ? w : "original"
    }
    readonly property bool _wash: _pal !== "original"
    // MacTahoe/WhiteSur Discord SVGs embed a Clyde face with broken aspect → bulgy/tiny eyes.
    // Prefer the stock hicolor PNG whenever the name smells like Discord.
    readonly property string resolvedName: {
        const n = String(name || "")
        const base = n.replace(/^file:\/\//, "").split("/").pop().toLowerCase()
        const isDiscord = /discord/.test(base) || /^(com\.discordapp\.)?discord/.test(n.toLowerCase())
        if (isDiscord)
            return "/usr/share/icons/hicolor/256x256/apps/discord.png"
        return n
    }
    // Icon= in .desktop is often an absolute path (AppImage, custom PNG). Quickshell.iconPath
    // only resolves theme names — a path was treated as a missing name and every such app
    // collapsed to the same fallback gear. Paths go straight to Image as file://.
    readonly property bool fileIcon: {
        const n = String(resolvedName || "")
        return n.startsWith("/") || n.startsWith("file:") || n.startsWith("image:")
    }
    readonly property string glyph: theme ? "" : (JD.glyph(name) || JD.glyph(fallback))
    implicitWidth: implicitSize
    implicitHeight: implicitSize
    Image {
        id: glyphImage
        anchors.fill: parent
        visible: !!ic.glyph && ic.tint === JD.text1
        source: ic.glyph ? Quickshell.shellDir + "/icons/" + ic.glyph + ".svg" : ""
        sourceSize: Qt.size(ic.renderSize, ic.renderSize)
        fillMode: Image.PreserveAspectFit
        mipmap: false
        smooth: true
        antialiasing: true
    }
    // Оба MultiEffect заводятся только когда нужны. Раньше они жили в каждом значке — в сетке меню это сотни
    // шейдерных объектов, которые ничего не рисуют (`visible: false`), но занимают память и время на создание (Р-42).
    Loader {
        anchors.fill: parent
        active: !!ic.glyph && ic.tint !== JD.text1
        sourceComponent: MultiEffect {
            source: glyphImage
            colorization: 1
            colorizationColor: ic.tint
            brightness: 1
        }
    }
    // Не IconImage из Quickshell: он жёстко просит растр по своему видимому размеру, и увеличенный
    // значок в доке расплывался. Здесь размер растра задаём сами.
    Image {
        id: themeImg
        anchors.fill: parent
        visible: !ic.glyph && !ic._wash
        source: {
            if (ic.fileIcon) {
                const n = String(ic.resolvedName || "")
                if (n.startsWith("file:") || n.startsWith("image:")) return n
                return "file://" + n
            }
            return Quickshell.iconPath(ic.resolvedName || ic.fallback, ic.fallback)
        }
        // Integer device pixels; mipmap off — mip chains soften fine glyph detail
        // (Discord eyes looked smaller / mushy on MacTahoe-style plates).
        sourceSize: Qt.size(Math.round(ic.renderSize), Math.round(ic.renderSize))
        fillMode: Image.PreserveAspectFit
        mipmap: false
        smooth: true
        antialiasing: true
        asynchronous: ic.loadAsync
    }
    // Затея со стеклом (iOS-подобная вуаль поверх значка): скрытая копия картинки и эффект над ней — только когда
    // вуаль включена. Keep colour, lift brightness, light colourization only.
    // Old light/clear used colorization:1 + saturation:0 → flat B&W plates.
    Loader {
        anchors.fill: parent
        active: !ic.glyph && ic._wash
        sourceComponent: Item {
            Image {
                id: themeImgSrc
                anchors.fill: parent
                visible: false
                source: themeImg.source
                sourceSize: Qt.size(Math.round(ic.renderSize), Math.round(ic.renderSize))
                fillMode: Image.PreserveAspectFit
                mipmap: false
                smooth: true
                antialiasing: true
                asynchronous: ic.loadAsync
            }
            MultiEffect {
                anchors.fill: parent
                source: themeImgSrc
                colorization: ic._pal === "mono" ? 0
                            : ic._pal === "tinted" ? 0.42
                            : ic._pal === "clear" ? 0.28
                            : 0.18   // light — soft frost, hue stays
                colorizationColor: ic._pal === "tinted" ? ic.iconPaletteTint
                                   : ic._pal === "clear" ? "#FFFFFF"
                                   : "#E8EEF6"
                brightness: ic._pal === "clear" ? 0.22
                          : ic._pal === "light" ? 0.14
                          : ic._pal === "tinted" ? 0.06
                          : 0.0
                saturation: ic._pal === "mono" ? 0
                          : ic._pal === "tinted" ? 0.55
                          : ic._pal === "clear" ? 0.75
                          : 0.90   // light keeps almost full colour
            }
        }
    }
}
