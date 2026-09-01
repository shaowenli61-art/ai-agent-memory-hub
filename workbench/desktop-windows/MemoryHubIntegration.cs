using System.IO;

namespace MemoryHubDesktop;

internal sealed record IntegrationRefreshResult(bool Success, string Message, DateTimeOffset CheckedAt);

internal sealed class MemoryHubIntegration : IDisposable
{
    private readonly string _snapshotPath;
    private readonly string _vaultRoot;
    private readonly List<FileSystemWatcher> _watchers = [];
    private readonly List<string> _allowedRoots = [];
    private readonly List<string> _vaultRoots = [];
    private readonly SemaphoreSlim _refreshGate = new(1, 1);
    private readonly Timer _debounceTimer;
    private bool _started;

    internal MemoryHubIntegration(string snapshotPath)
    {
        _snapshotPath = Path.GetFullPath(snapshotPath);
        var runtimeDirectory = Path.GetDirectoryName(_snapshotPath)
            ?? throw new ArgumentException("Snapshot path has no parent directory.");
        var memoryHubDirectory = Directory.GetParent(runtimeDirectory)?.FullName
            ?? throw new ArgumentException("Snapshot path must be inside .memory-hub/runtime.");
        _vaultRoot = Directory.GetParent(memoryHubDirectory)?.FullName
            ?? throw new ArgumentException("Snapshot path must be inside a Vault.");
        _debounceTimer = new Timer(_ => _ = RefreshAsync(), null, Timeout.Infinite, Timeout.Infinite);
        _allowedRoots.Add(_vaultRoot);
        _vaultRoots.Add(_vaultRoot);
        AddFileWatcher(_snapshotPath);
    }

    internal event EventHandler<IntegrationRefreshResult>? Refreshed;

    internal int WatchedSourceCount => _watchers.Count;

    internal void Start()
    {
        if (_started)
        {
            return;
        }

        _started = true;
        foreach (var watcher in _watchers)
        {
            watcher.EnableRaisingEvents = true;
        }
        RequestRefresh(0);
    }

    internal void RequestRefresh(int delayMilliseconds = 1200)
    {
        _debounceTimer.Change(delayMilliseconds, Timeout.Infinite);
    }

    internal bool TryResolveEvidenceTarget(string rawPath, out string target)
    {
        target = "";
        if (string.IsNullOrWhiteSpace(rawPath))
        {
            return false;
        }

        var fullPath = Path.GetFullPath(Path.IsPathRooted(rawPath) ? rawPath : Path.Combine(_vaultRoot, rawPath));
        if ((!File.Exists(fullPath) && !Directory.Exists(fullPath)) ||
            !_allowedRoots.Any(root => IsWithin(fullPath, root)))
        {
            return false;
        }

        if (File.Exists(fullPath) && string.Equals(Path.GetExtension(fullPath), ".md", StringComparison.OrdinalIgnoreCase))
        {
            var vaultRoot = _vaultRoots.FirstOrDefault(root => IsWithin(fullPath, root));
            if (vaultRoot is not null)
            {
                var relative = Path.GetRelativePath(vaultRoot, fullPath).Replace('\\', '/');
                var encodedRelative = Uri.EscapeDataString(relative).Replace("%2F", "/", StringComparison.OrdinalIgnoreCase);
                target = $"obsidian://open?vault={Uri.EscapeDataString(Path.GetFileName(vaultRoot))}&file={encodedRelative}";
                return true;
            }
        }

        target = fullPath;
        return true;
    }

    private void AddFileWatcher(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return;
        }

        var directory = Path.GetDirectoryName(path);
        var fileName = Path.GetFileName(path);
        if (directory is null || !Directory.Exists(directory))
        {
            return;
        }

        AddWatcher(directory, fileName, false);
    }

    private void AddWatcher(string path, string filter, bool includeSubdirectories)
    {
        var watcher = new FileSystemWatcher(path, filter)
        {
            IncludeSubdirectories = includeSubdirectories,
            NotifyFilter = NotifyFilters.FileName | NotifyFilters.LastWrite | NotifyFilters.CreationTime,
        };
        watcher.Changed += SourceChanged;
        watcher.Created += SourceChanged;
        watcher.Deleted += SourceChanged;
        watcher.Renamed += SourceChanged;
        _watchers.Add(watcher);
    }

    private void SourceChanged(object sender, FileSystemEventArgs e)
    {
        RequestRefresh();
    }

    private async Task RefreshAsync()
    {
        await _refreshGate.WaitAsync();
        try
        {
            var success = File.Exists(_snapshotPath);
            var message = success ? "本地记忆快照监听中" : "未找到记忆中枢快照";
            Refreshed?.Invoke(this, new(success, message, DateTimeOffset.Now));
        }
        catch (Exception exception)
        {
            Refreshed?.Invoke(this, new(false, exception.Message, DateTimeOffset.Now));
        }
        finally
        {
            _refreshGate.Release();
        }
    }

    private static bool IsWithin(string path, string root)
    {
        var relative = Path.GetRelativePath(root, path);
        return relative != ".." && !relative.StartsWith($"..{Path.DirectorySeparatorChar}", StringComparison.Ordinal);
    }

    public void Dispose()
    {
        _debounceTimer.Dispose();
        foreach (var watcher in _watchers)
        {
            watcher.Dispose();
        }
        _refreshGate.Dispose();
    }
}
