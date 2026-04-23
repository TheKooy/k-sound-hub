#include <LayerShellQt/Shell>
#include <LayerShellQt/Window>

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QFileSystemWatcher>
#include <QGuiApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMargins>
#include <QObject>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QScreen>
#include <QSize>
#include <QTimer>

class HudController : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString hudText READ hudText NOTIFY hudTextChanged)
    Q_PROPERTY(bool hudVisible READ hudVisible NOTIFY hudVisibleChanged)
    Q_PROPERTY(int durationMs READ durationMs NOTIFY durationMsChanged)
    Q_PROPERTY(bool mutedActive READ mutedActive NOTIFY mutedActiveChanged)

public:
    explicit HudController(const QString &statePath, QObject *parent = nullptr)
        : QObject(parent),
          m_statePath(statePath),
          m_watcher(new QFileSystemWatcher(this))
    {
        m_hideTimer.setSingleShot(true);

        connect(&m_hideTimer, &QTimer::timeout, this, [this]() {
            if (!m_hudVisible)
                return;

            m_hudVisible = false;
            emit hudVisibleChanged();
        });

        watchStateFile();

        connect(m_watcher, &QFileSystemWatcher::fileChanged, this, [this](const QString &) {
            QTimer::singleShot(20, this, [this]() {
                watchStateFile();
                loadStateFile();
            });
        });
    }

    QString hudText() const { return m_hudText; }
    bool hudVisible() const { return m_hudVisible; }
    int durationMs() const { return m_durationMs; }
    bool mutedActive() const { return m_mutedActive; }

signals:
    void hudTextChanged();
    void hudVisibleChanged();
    void durationMsChanged();
    void mutedActiveChanged();
    void triggerShow();

private:
    void watchStateFile()
    {
        const QStringList files = m_watcher->files();
        if (!files.isEmpty())
            m_watcher->removePaths(files);

        if (QFileInfo::exists(m_statePath))
            m_watcher->addPath(m_statePath);
    }

    void loadStateFile()
    {
        QFile file(m_statePath);
        if (!file.open(QIODevice::ReadOnly))
            return;

        const QByteArray raw = file.readAll();
        file.close();

        const auto doc = QJsonDocument::fromJson(raw);
        if (!doc.isObject())
            return;

        const QJsonObject obj = doc.object();
        const int seq = obj.value(QStringLiteral("seq")).toInt(-1);

        if (seq == m_lastSeq)
            return;

        m_lastSeq = seq;

        const QString newText = obj.value(QStringLiteral("text")).toString();
        const bool visible = obj.value(QStringLiteral("visible")).toBool(false);
        const int newDuration = obj.value(QStringLiteral("durationMs")).toInt(900);
        const bool newMutedActive = obj.value(QStringLiteral("mutedActive")).toBool(false);

        bool textChanged = false;
        bool visChanged = false;
        bool durationChanged = false;
        bool mutedChanged = false;

        if (newText != m_hudText) {
            m_hudText = newText;
            textChanged = true;
        }

        if (newDuration != m_durationMs) {
            m_durationMs = newDuration;
            durationChanged = true;
        }

        if (newMutedActive != m_mutedActive) {
            m_mutedActive = newMutedActive;
            mutedChanged = true;
        }

        if (visible) {
            if (!m_hudVisible) {
                m_hudVisible = true;
                visChanged = true;
            }

            m_hideTimer.start(m_durationMs);
            emit triggerShow();
        }

        if (textChanged)
            emit hudTextChanged();
        if (durationChanged)
            emit durationMsChanged();
        if (mutedChanged)
            emit mutedActiveChanged();
        if (visChanged)
            emit hudVisibleChanged();
    }

    QString m_statePath;
    QFileSystemWatcher *m_watcher = nullptr;
    QString m_hudText;
    bool m_hudVisible = false;
    int m_durationMs = 900;
    bool m_mutedActive = false;
    int m_lastSeq = -1;
    QTimer m_hideTimer;
};

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setApplicationName("audio-hud-overlay");

    const QString statePath =
        QDir::homePath() + QStringLiteral("/.config/audio-stack/hud_overlay/state.json");

    HudController controller(statePath);

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("hudController"), &controller);
    engine.loadFromModule("AudioHudOverlay", "Overlay");

    if (engine.rootObjects().isEmpty())
        return 1;

    auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    if (!window)
        return 1;

    auto *lsw = LayerShellQt::Window::get(window);
    if (!lsw)
        return 1;

    lsw->setLayer(LayerShellQt::Window::LayerOverlay);

    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorRight;
    lsw->setAnchors(anchors);

    lsw->setKeyboardInteractivity(LayerShellQt::Window::KeyboardInteractivityNone);
    lsw->setMargins(QMargins(0, 24, 24, 0));
    lsw->setExclusiveZone(-1);

    window->setScreen(QGuiApplication::primaryScreen());
    lsw->setDesiredSize(QSize(380, 92));

    QObject::connect(&controller, &HudController::triggerShow, window, [window]() {
        window->show();
        window->raise();
    });

    return app.exec();
}

#include "main.moc"
