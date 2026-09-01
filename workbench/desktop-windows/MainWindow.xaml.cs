using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;

namespace MemoryHubDesktop;

public partial class MainWindow : Window
{
    private readonly string _snapshotPath;
    private readonly string _webRoot;
    private readonly string _statePath;
    private readonly string _healthPath;
    private readonly MemoryHubIntegration _integration;
    private readonly DispatcherTimer _snapshotTimer;
    private IntPtr _windowHandle;
    private IntPtr _desktopAnchor;
    private DateTime _snapshotWriteTimeUtc;
    private double _dragOriginLeft;
    private double _dragOriginTop;
    private WindowPlacementState _placement = new(0, 16, true);
    private bool _webReady;

    public MainWindow(string[] args)
    {
        InitializeComponent();

        _snapshotPath = GetArgument(args, "--snapshot")
            ?? throw new ArgumentException("Start with --snapshot <vault\\.memory-hub\\runtime\\operations_snapshot.json>.");
        _webRoot = Path.Combine(AppContext.BaseDirectory, "web");
        _healthPath = Path.Combine(_webRoot, "data", "integration_health.json");
        _integration = new MemoryHubIntegration(_snapshotPath);
        _integration.Refreshed += Integration_Refreshed;
        _statePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "MemoryHubDesktopData",
            "window-state.json");

        _snapshotTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
        _snapshotTimer.Tick += SnapshotTimer_Tick;
        LoadPlacement();
    }

    private static string? GetArgument(IReadOnlyList<string> args, string name)
    {
        for (var index = 0; index < args.Count - 1; index++)
        {
            if (string.Equals(args[index], name, StringComparison.OrdinalIgnoreCase))
            {
                return args[index + 1];
            }
        }

        return null;
    }

    private void Window_SourceInitialized(object? sender, EventArgs e)
    {
        _windowHandle = new WindowInteropHelper(this).Handle;
        _desktopAnchor = DesktopHost.FindDesktopLayerAnchor();
        DesktopHost.MarkAsDesktopToolWindow(_windowHandle);
        DesktopHost.SetDesktopOwner(_windowHandle, _desktopAnchor);
        PositionWindow();
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        await InitializeWebViewAsync();
        WriteIntegrationHealth("starting", "正在连接 Obsidian 正式源", DateTimeOffset.Now);
        _integration.Start();
        _snapshotTimer.Start();
    }

    private async Task InitializeWebViewAsync()
    {
        Directory.CreateDirectory(_webRoot);
        SyncSnapshot();

        var userDataFolder = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "MemoryHubDesktopData",
            "WebView2");
        Directory.CreateDirectory(userDataFolder);

        var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: userDataFolder);
        await WorkbenchView.EnsureCoreWebView2Async(environment);
        WorkbenchView.DefaultBackgroundColor = System.Drawing.Color.Transparent;

        WorkbenchView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
        WorkbenchView.CoreWebView2.Settings.AreDevToolsEnabled = false;
        WorkbenchView.CoreWebView2.Settings.IsStatusBarEnabled = false;
        WorkbenchView.CoreWebView2.Settings.IsZoomControlEnabled = false;
        WorkbenchView.CoreWebView2.SetVirtualHostNameToFolderMapping(
            "memory-hub.local",
            _webRoot,
            CoreWebView2HostResourceAccessKind.Allow);
        WorkbenchView.CoreWebView2.WebMessageReceived += CoreWebView2_WebMessageReceived;
        WorkbenchView.CoreWebView2.NavigationCompleted += (_, _) =>
        {
            _webReady = true;
            Dispatcher.BeginInvoke(PositionWindow, DispatcherPriority.ContextIdle);
        };
        WorkbenchView.Source = new Uri("https://memory-hub.local/index.html");
    }

    private void SnapshotTimer_Tick(object? sender, EventArgs e)
    {
        if (!File.Exists(_snapshotPath))
        {
            return;
        }

        var currentWriteTime = File.GetLastWriteTimeUtc(_snapshotPath);
        if (currentWriteTime <= _snapshotWriteTimeUtc)
        {
            return;
        }

        SyncSnapshot();
        if (_webReady)
        {
            WorkbenchView.Reload();
        }
    }

    private void SyncSnapshot()
    {
        if (!File.Exists(_snapshotPath))
        {
            return;
        }

        var dataDirectory = Path.Combine(_webRoot, "data");
        Directory.CreateDirectory(dataDirectory);
        File.Copy(_snapshotPath, Path.Combine(dataDirectory, "operations_snapshot.json"), true);
        _snapshotWriteTimeUtc = File.GetLastWriteTimeUtc(_snapshotPath);
    }

    private void CoreWebView2_WebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        using var document = JsonDocument.Parse(e.WebMessageAsJson);
        var root = document.RootElement;
        if (!root.TryGetProperty("type", out var typeElement))
        {
            return;
        }

        switch (typeElement.GetString())
        {
            case "refresh":
                WriteIntegrationHealth("starting", "正在重建只读快照", DateTimeOffset.Now);
                _integration.RequestRefresh(0);
                break;
            case "open-evidence":
                if (root.TryGetProperty("path", out var pathElement))
                {
                    OpenEvidence(pathElement.GetString() ?? "");
                }
                break;
            case "close":
                Close();
                break;
            case "dock-right":
                _placement = _placement with { Docked = true };
                PositionWindow();
                SavePlacement();
                break;
            case "drag-start":
                _dragOriginLeft = Left;
                _dragOriginTop = Top;
                _placement = _placement with { Docked = false };
                break;
            case "drag-move":
                MoveFromMessage(root);
                break;
            case "drag-end":
                SaveCurrentPosition();
                break;
        }
    }

    private void Integration_Refreshed(object? sender, IntegrationRefreshResult result)
    {
        Dispatcher.BeginInvoke(() =>
        {
            WriteIntegrationHealth(result.Success ? "live" : "error", result.Message, result.CheckedAt);
            if (result.Success)
            {
                SyncSnapshot();
            }
            if (_webReady)
            {
                WorkbenchView.Reload();
            }
        });
    }

    private void WriteIntegrationHealth(string status, string message, DateTimeOffset checkedAt)
    {
        var directory = Path.GetDirectoryName(_healthPath)!;
        Directory.CreateDirectory(directory);
        var temporaryPath = $"{_healthPath}.tmp";
        var payload = new
        {
            status,
            message,
            checked_at = checkedAt.ToString("O"),
            watched_sources = _integration.WatchedSourceCount,
            mode = "read_only",
        };
        File.WriteAllText(temporaryPath, JsonSerializer.Serialize(payload));
        File.Move(temporaryPath, _healthPath, true);
    }

    private void OpenEvidence(string path)
    {
        if (_integration.TryResolveEvidenceTarget(path, out var target))
        {
            Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
        }
    }

    private void MoveFromMessage(JsonElement root)
    {
        if (!root.TryGetProperty("dx", out var dxElement) || !root.TryGetProperty("dy", out var dyElement))
        {
            return;
        }

        Left = _dragOriginLeft + dxElement.GetDouble();
        Top = _dragOriginTop + dyElement.GetDouble();
        DesktopHost.PlaceBehindNormalWindows(_windowHandle, _desktopAnchor);
    }

    private void PositionWindow()
    {
        if (_windowHandle == IntPtr.Zero)
        {
            return;
        }

        var workArea = SystemParameters.WorkArea;
        Width = 420;
        Height = Math.Max(MinHeight, workArea.Height);
        Left = _placement.Docked ? workArea.Right - Width : _placement.X;
        Top = _placement.Docked ? workArea.Top : _placement.Y;
        DesktopHost.PlaceBehindNormalWindows(_windowHandle, _desktopAnchor);
        Dispatcher.BeginInvoke(
            () => DesktopHost.ApplyLeftCornerRegion(_windowHandle, 32),
            DispatcherPriority.Loaded);
    }

    private void LoadPlacement()
    {
        if (!File.Exists(_statePath))
        {
            return;
        }

        var state = JsonSerializer.Deserialize<WindowPlacementState>(File.ReadAllText(_statePath));
        if (state is not null)
        {
            _placement = state;
        }
    }

    private void SaveCurrentPosition()
    {
        _placement = new WindowPlacementState((int)Math.Round(Left), (int)Math.Round(Top), false);
        SavePlacement();
    }

    private void SavePlacement()
    {
        var directory = Path.GetDirectoryName(_statePath)!;
        Directory.CreateDirectory(directory);
        File.WriteAllText(_statePath, JsonSerializer.Serialize(_placement));
    }

    protected override void OnClosed(EventArgs e)
    {
        _snapshotTimer.Stop();
        _integration.Refreshed -= Integration_Refreshed;
        _integration.Dispose();
        base.OnClosed(e);
    }
}

internal sealed record WindowPlacementState(int X, int Y, bool Docked);

internal static class DesktopHost
{
    private const uint SpawnWorkerMessage = 0x052C;

    internal static IntPtr FindDesktopLayerAnchor()
    {
        var progman = FindWindow("Progman", null);
        if (progman == IntPtr.Zero)
        {
            return IntPtr.Zero;
        }

        SendMessageTimeout(progman, SpawnWorkerMessage, new IntPtr(0xD), IntPtr.Zero, 0, 1000, out _);
        SendMessageTimeout(progman, SpawnWorkerMessage, new IntPtr(0xD), new IntPtr(1), 0, 1000, out _);

        var iconHost = IntPtr.Zero;
        EnumWindows((topWindow, _) =>
        {
            var shellView = FindWindowEx(topWindow, IntPtr.Zero, "SHELLDLL_DefView", null);
            if (shellView == IntPtr.Zero)
            {
                return true;
            }

            iconHost = topWindow;
            return false;
        }, IntPtr.Zero);

        return iconHost != IntPtr.Zero ? iconHost : progman;
    }

    internal static void MarkAsDesktopToolWindow(IntPtr window)
    {
        const int extendedStyleIndex = -20;
        const long appWindowStyle = 0x00040000L;
        const long toolWindowStyle = 0x00000080L;
        var styles = GetWindowLongPtr(window, extendedStyleIndex).ToInt64();
        styles = (styles & ~appWindowStyle) | toolWindowStyle;
        SetWindowLongPtr(window, extendedStyleIndex, new IntPtr(styles));
    }

    internal static void SetDesktopOwner(IntPtr window, IntPtr desktopAnchor)
    {
        if (desktopAnchor == IntPtr.Zero)
        {
            return;
        }

        const int ownerIndex = -8;
        SetWindowLongPtr(window, ownerIndex, desktopAnchor);
    }

    internal static void PlaceBehindNormalWindows(IntPtr window, IntPtr desktopAnchor)
    {
        if (window == IntPtr.Zero || desktopAnchor == IntPtr.Zero)
        {
            return;
        }

        const int noSize = 0x0001;
        const int noMove = 0x0002;
        const int noActivate = 0x0010;
        const int showWindow = 0x0040;
        SetWindowPos(window, desktopAnchor, 0, 0, 0, 0, noSize | noMove | noActivate | showWindow);
    }

    internal static void ApplyLeftCornerRegion(IntPtr window, int logicalRadius)
    {
        if (window == IntPtr.Zero || !GetWindowRect(window, out var rect))
        {
            return;
        }

        var scale = GetDpiForWindow(window) / 96d;
        var radius = Math.Max(1, (int)Math.Round(logicalRadius * scale));
        var width = rect.Right - rect.Left;
        var height = rect.Bottom - rect.Top;
        var rounded = CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2);
        var squareRight = CreateRectRgn(width - radius, 0, width + 1, height + 1);
        var combined = CreateRectRgn(0, 0, 0, 0);

        CombineRgn(combined, rounded, squareRight, 2);
        DeleteObject(rounded);
        DeleteObject(squareRight);
        if (SetWindowRgn(window, combined, true) == 0)
        {
            DeleteObject(combined);
        }
    }

    internal delegate bool EnumWindowsProc(IntPtr window, IntPtr parameter);

    [DllImport("user32.dll", SetLastError = true)]
    internal static extern bool SetWindowPos(
        IntPtr window,
        IntPtr insertAfter,
        int x,
        int y,
        int width,
        int height,
        int flags);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetWindowRect(IntPtr window, out NativeRect rect);

    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr window);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(
        int left,
        int top,
        int right,
        int bottom,
        int ellipseWidth,
        int ellipseHeight);

    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRectRgn(int left, int top, int right, int bottom);

    [DllImport("gdi32.dll")]
    private static extern int CombineRgn(IntPtr destination, IntPtr source1, IntPtr source2, int mode);

    [DllImport("user32.dll")]
    private static extern int SetWindowRgn(IntPtr window, IntPtr region, bool redraw);

    [DllImport("gdi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DeleteObject(IntPtr graphicsObject);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr GetWindowLongPtr(IntPtr window, int index);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr SetWindowLongPtr(IntPtr window, int index, IntPtr newValue);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string? className, string? windowName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindowEx(IntPtr parent, IntPtr childAfter, string? className, string? windowName);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SendMessageTimeout(
        IntPtr window,
        uint message,
        IntPtr wParam,
        IntPtr lParam,
        uint flags,
        uint timeout,
        out IntPtr result);
}

[StructLayout(LayoutKind.Sequential)]
internal struct NativeRect
{
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}
