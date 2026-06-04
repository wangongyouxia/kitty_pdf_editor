using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>
/// UI-facing wrapper around <see cref="PdfDocument"/>: tracks the file
/// path, dirty state, and a bounded undo/redo history.  Every mutating
/// edit goes through <see cref="Mutate"/>, which snapshots the current
/// bytes for undo, applies the change, and reloads.
///
/// Reloading after each edit (rather than holding one long-lived native
/// doc) keeps element indices honest: PDFium regenerates content on each
/// edit, and re-opening guarantees GetElements indices line up with what
/// the next edit will mutate.
/// </summary>
public sealed class PdfSession : IDisposable
{
    private const int UndoLimit = 40;

    private PdfDocument? _doc;
    private readonly Stack<byte[]> _undo = new();
    private readonly Stack<byte[]> _redo = new();

    public string? Path { get; private set; }
    public bool IsOpen => _doc != null;
    public bool Dirty { get; private set; }
    public int PageCount => _doc?.PageCount ?? 0;

    public event Action? Changed;          // document replaced (open/undo/redo/edit)
    public event Action<bool>? DirtyChanged;

    public PdfDocument Document =>
        _doc ?? throw new InvalidOperationException("no document open");

    public void Open(string path)
    {
        var doc = PdfDocument.Open(path);
        _doc?.Dispose();
        _doc = doc;
        Path = path;
        _undo.Clear();
        _redo.Clear();
        SetDirty(false);
        Changed?.Invoke();
    }

    public void Close()
    {
        _doc?.Dispose();
        _doc = null;
        Path = null;
        _undo.Clear();
        _redo.Clear();
        SetDirty(false);
        Changed?.Invoke();
    }

    /// <summary>
    /// Run a mutating edit against the live document.  Snapshots for undo,
    /// invokes <paramref name="edit"/>, then reloads from the new bytes.
    /// </summary>
    public void Mutate(Action<PdfDocument> edit)
    {
        if (_doc == null) return;
        byte[] before = _doc.SaveToBytes();
        edit(_doc);
        byte[] after = _doc.SaveToBytes();

        _undo.Push(before);
        if (_undo.Count > UndoLimit)
        {
            // Trim oldest by rebuilding (Stack has no bounded API).
            var keep = _undo.ToArray()[..UndoLimit];
            _undo.Clear();
            for (int i = keep.Length - 1; i >= 0; i--) _undo.Push(keep[i]);
        }
        _redo.Clear();
        ReloadFrom(after);
        SetDirty(true);
    }

    /// <summary>
    /// Like <see cref="Mutate"/> but for operations that build a brand-new
    /// document (reorder, duplicate, merge-into-current): the producer
    /// returns the replacement bytes.
    /// </summary>
    public void MutateReplace(Func<PdfDocument, byte[]> produce)
    {
        if (_doc == null) return;
        byte[] before = _doc.SaveToBytes();
        byte[] after = produce(_doc);
        _undo.Push(before);
        _redo.Clear();
        ReloadFrom(after);
        SetDirty(true);
    }

    public bool CanUndo => _undo.Count > 0;
    public bool CanRedo => _redo.Count > 0;

    public void Undo()
    {
        if (_doc == null || _undo.Count == 0) return;
        _redo.Push(_doc.SaveToBytes());
        ReloadFrom(_undo.Pop());
        SetDirty(true);
    }

    public void Redo()
    {
        if (_doc == null || _redo.Count == 0) return;
        _undo.Push(_doc.SaveToBytes());
        ReloadFrom(_redo.Pop());
        SetDirty(true);
    }

    private void ReloadFrom(byte[] bytes)
    {
        _doc?.Dispose();
        _doc = PdfDocument.Load(bytes);
        Changed?.Invoke();
    }

    public void Save(string? path = null)
    {
        if (_doc == null) return;
        string target = path ?? Path ?? throw new InvalidOperationException("no path");
        _doc.SaveToFile(target);
        Path = target;
        SetDirty(false);
    }

    private void SetDirty(bool v)
    {
        if (Dirty == v) return;
        Dirty = v;
        DirtyChanged?.Invoke(v);
    }

    public void Dispose() => _doc?.Dispose();
}
