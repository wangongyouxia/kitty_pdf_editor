using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>
/// Owns the editable overlay.  When active, every page object on a
/// visible page gets an <see cref="ElementAdorner"/> on that page's
/// overlay canvas.  All commits route through <see cref="PdfSession.Mutate"/>
/// so undo/redo and dirty tracking come for free, and — critically —
/// every mutation is an element-level PDFium edit that leaves the font
/// resource untouched.
/// </summary>
public sealed class EditController
{
    private readonly MainWindow _window;
    private readonly PdfSession _session;
    private readonly Dictionary<PageHost, List<ElementAdorner>> _adorners = new();
    private readonly HashSet<PageHost> _built = new();
    private readonly InspectorPanel _inspector = new();

    private List<PageHost> _hosts = new();
    private bool _active;

    public ElementAdorner? Selected { get; private set; }

    // ---- Drawing tool state ----
    public DrawTool Tool { get; private set; } = DrawTool.Select;
    public Color StrokeColor { get; set; } = Colors.Red;
    public double StrokeWidth { get; set; } = 2.0;
    public byte[]? PendingImageBgra { get; set; }  // for image/signature placement
    public int PendingImageW { get; set; }
    public int PendingImageH { get; set; }

    public event Action? ToolChanged;

    public void SetTool(DrawTool tool)
    {
        Tool = tool;
        foreach (var list in _adorners.Values)
            foreach (var a in list)
                a.IsHitTestVisible = tool == DrawTool.Select;
        foreach (var h in _built) h.Draw.IsHitTestVisible = tool != DrawTool.Select;
        ToolChanged?.Invoke();
    }

    public EditController(MainWindow window, PdfSession session)
    {
        _window = window;
        _session = session;
        _inspector.Attach(this);
    }

    public bool IsActive => _active;

    public void Rebuild(List<PageHost> hosts)
    {
        Clear();
        _hosts = hosts;
    }

    public void SetActive(bool active)
    {
        _active = active;
        if (active)
        {
            _window.InspectorSlot.Content = _inspector;
            _inspector.ShowNone();
            // Overlays are built lazily by EnsureOverlay as pages become
            // visible (driven by MainWindow.RenderVisible).
        }
        else
        {
            Clear();
            _window.InspectorSlot.Content = null;
        }
    }

    public void OnZoomChanged()
    {
        // Bounds are zoom-dependent; cheapest correct path is a full
        // rebuild of already-built pages.
        foreach (var h in _built.ToList()) RebuildPage(h);
    }

    /// <summary>Build adorners for a page if active and not yet built.</summary>
    public void EnsureOverlay(PageHost host)
    {
        if (!_active || _built.Contains(host)) return;
        BuildPage(host);
    }

    public void RebuildPage(PageHost host)
    {
        ClearPage(host);
        if (_active) BuildPage(host);
    }

    private void BuildPage(PageHost host)
    {
        host.Draw.Controller = this;
        host.Draw.IsHitTestVisible = Tool != DrawTool.Select;

        var list = new List<ElementAdorner>();
        IReadOnlyList<PdfElement> els;
        try { els = _session.Document.GetElements(host.PageIndex); }
        catch { return; }

        // Sort so smaller elements sit on top (clickable when overlapping).
        foreach (var el in els)
        {
            if (el.Kind != PdfElementKind.Text && el.Kind != PdfElementKind.Image)
                continue; // skip paths/shadings for now — not directly editable
            if (el.Width <= 0 || el.Height <= 0) continue;
            var a = new ElementAdorner(this, host, el) { IsHitTestVisible = Tool == DrawTool.Select };
            host.Overlay.Children.Add(a);
            list.Add(a);
        }
        // z-order: smaller area on top.
        double maxArea = 1;
        foreach (var a in list) maxArea = Math.Max(maxArea, a.Element.Width * a.Element.Height);
        foreach (var a in list)
        {
            double area = Math.Max(1, a.Element.Width * a.Element.Height);
            Panel.SetZIndex(a, (int)(1000 * (1 - area / maxArea)));
        }
        _adorners[host] = list;
        _built.Add(host);
    }

    private void ClearPage(PageHost host)
    {
        if (_adorners.TryGetValue(host, out var list))
        {
            foreach (var a in list) host.Overlay.Children.Remove(a);
            _adorners.Remove(host);
        }
        // Remove leftover adorners / inline editors but KEEP the DrawingLayer.
        for (int i = host.Overlay.Children.Count - 1; i >= 0; i--)
        {
            var c = host.Overlay.Children[i];
            if (c is ElementAdorner || c is TextBox) host.Overlay.Children.RemoveAt(i);
        }
        _built.Remove(host);
        _handles?.Dispose();
        _handles = null;
        Selected = null;
    }

    public void Clear()
    {
        foreach (var h in _hosts) ClearPage(h);
        _adorners.Clear();
        _built.Clear();
        Selected = null;
    }

    // ------------------------------------------------------------------
    // Selection
    // ------------------------------------------------------------------
    private ResizeHandles? _handles;

    public void Select(ElementAdorner adorner)
    {
        if (Selected == adorner) return;
        Selected?.SetSelected(false);
        _handles?.Dispose();
        _handles = null;
        Selected = adorner;
        adorner.SetSelected(true);
        _inspector.Show(adorner);
        var host = FindHost(adorner);
        if (host != null && Tool == DrawTool.Select)
            _handles = new ResizeHandles(this, host, adorner);
    }

    /// <summary>Test hook: select the first element on a page (for screenshots).</summary>
    public bool SelectFirst(PageHost host)
    {
        if (_adorners.TryGetValue(host, out var list) && list.Count > 0)
        {
            Select(list[0]);
            return true;
        }
        return false;
    }

    public void ClearSelectionVisuals()
    {
        _handles?.Dispose();
        _handles = null;
        Selected?.SetSelected(false);
        Selected = null;
    }

    public void RepositionHandles() => _handles?.Reposition();

    /// <summary>Commit a resize: map the adorner's new screen rect to PDF.</summary>
    public void CommitResize(ElementAdorner adorner, double newLeftPx, double newTopPx,
        double newWpx, double newHpx)
    {
        var el = adorner.Element;
        double z = adorner.Zoom, pageH = adorner.PageHeightPt;
        double newL = newLeftPx / z;
        double newR = (newLeftPx + newWpx) / z;
        double newT = pageH - newTopPx / z;
        double newB = pageH - (newTopPx + newHpx) / z;
        int page = el.PageIndex, idx = el.Index;
        double oldL = el.Left, oldB = el.Bottom, oldR = el.Right, oldT = el.Top;
        _session.Mutate(d => d.TransformElementToRect(page, idx, oldL, oldB, oldR, oldT, newL, newB, newR, newT));
    }

    // ------------------------------------------------------------------
    // Commits — element-level edits, font preserved by construction
    // ------------------------------------------------------------------
    public void CommitMove(ElementAdorner adorner, double dxPt, double dyPt)
    {
        int page = adorner.Element.PageIndex;
        int idx = adorner.Element.Index;
        _session.Mutate(d => d.MoveElement(page, idx, dxPt, dyPt));
        // session.Changed → MainWindow rebuilds hosts + overlays.
    }

    public void CommitText(ElementAdorner adorner, string newText)
    {
        var el = adorner.Element;
        if (newText == el.Text) return;
        int page = el.PageIndex, idx = el.Index;
        string oldText = el.Text ?? "";
        string? fn = el.FontName; double sz = el.FontSize; bool bold = el.IsBold; bool italic = el.IsItalic;
        // EditText keeps the exact embedded font when the new text needs no
        // new glyphs; otherwise it rebuilds the run in place (one element)
        // using the full version of the original typeface.
        _session.Mutate(d => d.EditText(page, idx, newText, oldText, fn, sz, bold, italic));
    }

    public void CommitDelete(ElementAdorner adorner)
    {
        int page = adorner.Element.PageIndex;
        int idx = adorner.Element.Index;
        _session.Mutate(d => d.DeleteElement(page, idx));
    }

    // ------------------------------------------------------------------
    // Inline text editor: a TextBox placed over the adorner.
    // ------------------------------------------------------------------
    public void BeginInlineEdit(ElementAdorner adorner)
    {
        if (adorner.Element.Kind != PdfElementKind.Text) return;
        var host = FindHost(adorner);
        if (host == null) return;

        var box = new TextBox
        {
            Text = adorner.Element.Text ?? "",
            FontSize = Math.Max(10, adorner.Element.FontSize * adorner.Zoom * 0.9),
            FontFamily = new FontFamily("Microsoft YaHei"),
            FontWeight = adorner.Element.IsBold ? FontWeights.Bold : FontWeights.Normal,
            FontStyle = adorner.Element.IsItalic ? FontStyles.Italic : FontStyles.Normal,
            BorderThickness = new Thickness(2),
            BorderBrush = new SolidColorBrush(Color.FromRgb(0, 100, 200)),
            Background = new SolidColorBrush(Color.FromRgb(255, 252, 200)),
            AcceptsReturn = false,
        };
        double left = Canvas.GetLeft(adorner);
        double top = Canvas.GetTop(adorner);
        Canvas.SetLeft(box, left - 4);
        Canvas.SetTop(box, top - 4);
        box.MinWidth = Math.Max(120, adorner.Width + 8);
        box.Height = Math.Max(28, adorner.Height + 8);
        Panel.SetZIndex(box, 100000);
        host.Overlay.Children.Add(box);
        box.Focus();
        box.SelectAll();

        bool committed = false;
        void Commit()
        {
            if (committed) return;
            committed = true;
            string newText = box.Text;
            host.Overlay.Children.Remove(box);
            CommitText(adorner, newText);
        }
        box.LostKeyboardFocus += (_, _) => Commit();
        box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { Commit(); e.Handled = true; }
            else if (e.Key == Key.Escape)
            {
                committed = true;
                host.Overlay.Children.Remove(box);
                e.Handled = true;
            }
        };
    }

    private PageHost? FindHost(ElementAdorner adorner)
    {
        foreach (var kv in _adorners)
            if (kv.Value.Contains(adorner)) return kv.Key;
        return null;
    }

    // ------------------------------------------------------------------
    // Drawing commits.  The DrawingLayer passes PDF-point coordinates.
    // ------------------------------------------------------------------
    private PdfDocument.Rgba Stroke =>
        new(StrokeColor.R / 255.0, StrokeColor.G / 255.0, StrokeColor.B / 255.0, 1.0);

    // After committing a draw/insert, return to the Select tool so the
    // just-added element is immediately movable (and we don't keep
    // stamping more on the next click).  Set BEFORE Mutate so the overlay
    // rebuild comes up in Select mode.
    private void ReturnToSelect()
    {
        Tool = DrawTool.Select;
        ToolChanged?.Invoke();
    }

    public void CommitRect(int page, double x, double y, double w, double h)
    { ReturnToSelect(); _session.Mutate(d => d.AddRect(page, x, y, w, h, Stroke, null, StrokeWidth)); }

    public void CommitEllipse(int page, double cx, double cy, double rx, double ry)
    { ReturnToSelect(); _session.Mutate(d => d.AddEllipse(page, cx, cy, rx, ry, Stroke, null, StrokeWidth)); }

    public void CommitLine(int page, double x1, double y1, double x2, double y2, bool arrow)
    { ReturnToSelect(); _session.Mutate(d => d.AddLine(page, x1, y1, x2, y2, Stroke, StrokeWidth, arrow)); }

    public void CommitHighlight(int page, double x, double y, double w, double h)
    {
        ReturnToSelect();
        _session.Mutate(d => d.AddHighlight(page, x, y, w, h,
            (StrokeColor.R / 255.0, StrokeColor.G / 255.0, StrokeColor.B / 255.0)));
    }

    public void CommitInk(int page, IReadOnlyList<IReadOnlyList<(double, double)>> strokes)
    { ReturnToSelect(); _session.Mutate(d => d.AddInk(page, strokes, Stroke, StrokeWidth)); }

    public void CommitInsertText(int page, double x, double y, string text, double sizePt)
    {
        ReturnToSelect();
        _session.Mutate(d => d.InsertText(page, text, x, y, sizePt,
            (StrokeColor.R / 255.0, StrokeColor.G / 255.0, StrokeColor.B / 255.0, 1.0)));
    }

    public void CommitInsertImage(int page, double x, double y, double w, double h)
    {
        if (PendingImageBgra == null) return;
        var bytes = PendingImageBgra; int iw = PendingImageW, ih = PendingImageH;
        PendingImageBgra = null;       // one-shot placement
        ReturnToSelect();
        _session.Mutate(d => d.InsertImage(page, bytes, iw, ih, x, y, w, h));
    }
}

public enum DrawTool
{
    Select, Rect, Ellipse, Line, Arrow, Highlight, Ink, Text, Image,
}
