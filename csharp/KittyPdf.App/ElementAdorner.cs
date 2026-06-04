using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>
/// The selectable / movable overlay box for one page object.  Lives on a
/// <see cref="PageHost.Overlay"/> canvas.  Geometry is kept in screen
/// (canvas) coordinates; on commit it converts deltas back to PDF points
/// and asks the controller to mutate the document.
/// </summary>
public sealed class ElementAdorner : Border
{
    private readonly EditController _ctrl;
    private readonly PageHost _host;
    public PdfElement Element { get; }

    private Point _dragStart;
    private double _startLeft, _startTop;
    private bool _dragging;
    private bool _movedDuringDrag;
    private bool _wasSelectedAtPress;

    private static readonly Brush TextStroke = new SolidColorBrush(Color.FromArgb(230, 70, 110, 220));
    private static readonly Brush ImageStroke = new SolidColorBrush(Color.FromArgb(230, 220, 100, 60));
    private static readonly Brush SelectedStroke = new SolidColorBrush(Color.FromArgb(255, 0, 120, 215));

    public ElementAdorner(EditController ctrl, PageHost host, PdfElement el)
    {
        _ctrl = ctrl;
        _host = host;
        Element = el;

        Background = Brushes.Transparent;
        BorderThickness = new Thickness(1);
        BorderBrush = el.Kind == PdfElementKind.Image ? ImageStroke : TextStroke;
        Focusable = true;
        Cursor = Cursors.SizeAll;
        ToolTip = el.Kind == PdfElementKind.Text ? $"文字：{Trim(el.Text)}" : $"{el.Kind}";
        SnapsToDevicePixels = true;

        Place();
    }

    private static string Trim(string? s)
        => s == null ? "" : (s.Length > 40 ? s[..40] + "…" : s);

    public double Zoom => _host.Zoom;

    /// <summary>Position the box from the element's PDF bounds (y-up → y-down).</summary>
    public void Place()
    {
        double z = _host.Zoom;
        double left = Element.Left * z;
        double top = (_host.PageHeightPt - Element.Top) * z;
        Canvas.SetLeft(this, left);
        Canvas.SetTop(this, top);
        Width = Math.Max(3, Element.Width * z);
        Height = Math.Max(3, Element.Height * z);
    }

    public void SetSelected(bool selected)
    {
        BorderThickness = new Thickness(selected ? 2 : 1);
        BorderBrush = selected ? SelectedStroke
            : (Element.Kind == PdfElementKind.Image ? ImageStroke : TextStroke);
    }

    // ------------------------------------------------------------------
    // Mouse: select + drag-move
    // ------------------------------------------------------------------
    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonDown(e);
        _wasSelectedAtPress = _ctrl.Selected == this;
        _ctrl.Select(this);
        Focus();
        if (e.ClickCount == 2 && Element.Kind == PdfElementKind.Text)
        {
            _ctrl.BeginInlineEdit(this);
            e.Handled = true;
            return;
        }
        _dragStart = e.GetPosition(_host.Overlay);
        _startLeft = Canvas.GetLeft(this);
        _startTop = Canvas.GetTop(this);
        _dragging = true;
        _movedDuringDrag = false;
        CaptureMouse();
        e.Handled = true;
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        base.OnMouseMove(e);
        if (!_dragging) return;
        var p = e.GetPosition(_host.Overlay);
        double dx = p.X - _dragStart.X;
        double dy = p.Y - _dragStart.Y;
        if (Math.Abs(dx) > 1 || Math.Abs(dy) > 1) _movedDuringDrag = true;
        Canvas.SetLeft(this, _startLeft + dx);
        Canvas.SetTop(this, _startTop + dy);
    }

    protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
    {
        base.OnMouseLeftButtonUp(e);
        if (!_dragging) return;
        _dragging = false;
        ReleaseMouseCapture();

        if (_movedDuringDrag)
        {
            double newLeft = Canvas.GetLeft(this);
            double newTop = Canvas.GetTop(this);
            double z = _host.Zoom;
            double dxPt = (newLeft - _startLeft) / z;
            double dyPt = -(newTop - _startTop) / z;   // screen y-down → PDF y-up
            if (Math.Abs(dxPt) > 0.01 || Math.Abs(dyPt) > 0.01)
                _ctrl.CommitMove(this, dxPt, dyPt);
        }
        else if (_wasSelectedAtPress && Element.Kind == PdfElementKind.Text)
        {
            // Click on an already-selected text box → inline edit (WPS-style).
            _ctrl.BeginInlineEdit(this);
        }
        e.Handled = true;
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        if (e.Key is Key.Delete or Key.Back)
        {
            _ctrl.CommitDelete(this);
            e.Handled = true;
        }
    }
}
