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
            var a = new ElementAdorner(this, host, el);
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
        host.Overlay.Children.Clear();
        _built.Remove(host);
        if (Selected != null && !host.Overlay.Children.Contains(Selected))
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
    public void Select(ElementAdorner adorner)
    {
        if (Selected == adorner) return;
        Selected?.SetSelected(false);
        Selected = adorner;
        adorner.SetSelected(true);
        _inspector.Show(adorner);
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
        if (newText == adorner.Element.Text) return;
        int page = adorner.Element.PageIndex;
        int idx = adorner.Element.Index;
        _session.Mutate(d => d.SetElementText(page, idx, newText));
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
}
