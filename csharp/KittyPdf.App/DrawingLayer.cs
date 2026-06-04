using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace KittyPdf.App;

/// <summary>
/// Transparent capture surface over a page.  Active only when a drawing
/// tool is selected; turns mouse drags into shape commits (converting
/// screen px → PDF points, y-down → y-up).
/// </summary>
public sealed class DrawingLayer : Canvas
{
    private readonly PageHost _host;
    public EditController? Controller { get; set; }

    private Point _start;
    private bool _dragging;
    private Shape? _preview;
    private Polyline? _inkPreview;
    private readonly List<(double, double)> _inkPts = new();

    public DrawingLayer(PageHost host)
    {
        _host = host;
        Background = Brushes.Transparent;
        ClipToBounds = true;
    }

    private DrawTool Tool => Controller?.Tool ?? DrawTool.Select;
    private double Zoom => _host.Zoom;
    private double PageH => _host.PageHeightPt;

    private (double x, double y) ToPdf(Point p) => (p.X / Zoom, PageH - p.Y / Zoom);

    protected override void OnMouseLeftButtonDown(MouseButtonEventArgs e)
    {
        if (Controller == null || Tool == DrawTool.Select) return;
        _start = e.GetPosition(this);
        _dragging = true;
        CaptureMouse();

        var brush = new SolidColorBrush(Controller.StrokeColor);
        switch (Tool)
        {
            case DrawTool.Rect:
            case DrawTool.Highlight:
                _preview = new Rectangle { Stroke = brush, StrokeThickness = 1.5,
                    Fill = Tool == DrawTool.Highlight ? new SolidColorBrush(Color.FromArgb(80, brush.Color.R, brush.Color.G, brush.Color.B)) : Brushes.Transparent };
                break;
            case DrawTool.Ellipse:
                _preview = new Ellipse { Stroke = brush, StrokeThickness = 1.5, Fill = Brushes.Transparent };
                break;
            case DrawTool.Line:
            case DrawTool.Arrow:
                _preview = new Line { Stroke = brush, StrokeThickness = 1.5 };
                break;
            case DrawTool.Ink:
                _inkPts.Clear();
                _inkPts.Add(ToPdf(_start));
                _inkPreview = new Polyline { Stroke = brush, StrokeThickness = 1.5 };
                _inkPreview.Points.Add(_start);
                Children.Add(_inkPreview);
                break;
            case DrawTool.Text:
                _dragging = false; ReleaseMouseCapture();
                CommitText(_start);
                return;
            case DrawTool.Image:
                _dragging = false; ReleaseMouseCapture();
                CommitImage(_start);
                return;
        }
        if (_preview != null) Children.Add(_preview);
        e.Handled = true;
    }

    protected override void OnMouseMove(MouseEventArgs e)
    {
        if (!_dragging) return;
        var p = e.GetPosition(this);
        if (Tool == DrawTool.Ink && _inkPreview != null)
        {
            _inkPreview.Points.Add(p);
            _inkPts.Add(ToPdf(p));
            return;
        }
        double x = Math.Min(_start.X, p.X), y = Math.Min(_start.Y, p.Y);
        double w = Math.Abs(p.X - _start.X), h = Math.Abs(p.Y - _start.Y);
        switch (_preview)
        {
            case Rectangle r:
                SetLeft(r, x); SetTop(r, y); r.Width = w; r.Height = h; break;
            case Ellipse el:
                SetLeft(el, x); SetTop(el, y); el.Width = w; el.Height = h; break;
            case Line ln:
                ln.X1 = _start.X; ln.Y1 = _start.Y; ln.X2 = p.X; ln.Y2 = p.Y; break;
        }
    }

    protected override void OnMouseLeftButtonUp(MouseButtonEventArgs e)
    {
        if (!_dragging || Controller == null) return;
        _dragging = false;
        ReleaseMouseCapture();
        var p = e.GetPosition(this);
        int page = _host.PageIndex;

        // Clear previews before committing (commit triggers a rebuild).
        if (_preview != null) { Children.Remove(_preview); _preview = null; }
        var inkPrev = _inkPreview; _inkPreview = null;
        if (inkPrev != null) Children.Remove(inkPrev);

        var (sx, sy) = ToPdf(_start);
        var (ex, ey) = ToPdf(p);
        double x = Math.Min(sx, ex), y = Math.Min(sy, ey);
        double w = Math.Abs(ex - sx), h = Math.Abs(ey - sy);

        switch (Tool)
        {
            case DrawTool.Rect when w > 2 && h > 2: Controller.CommitRect(page, x, y, w, h); break;
            case DrawTool.Highlight when w > 2 && h > 2: Controller.CommitHighlight(page, x, y, w, h); break;
            case DrawTool.Ellipse when w > 2 && h > 2:
                Controller.CommitEllipse(page, (sx + ex) / 2, (sy + ey) / 2, w / 2, h / 2); break;
            case DrawTool.Line: Controller.CommitLine(page, sx, sy, ex, ey, arrow: false); break;
            case DrawTool.Arrow: Controller.CommitLine(page, sx, sy, ex, ey, arrow: true); break;
            case DrawTool.Ink when _inkPts.Count >= 2:
                Controller.CommitInk(page, new List<IReadOnlyList<(double, double)>> { _inkPts.ToList() }); break;
        }
        e.Handled = true;
    }

    private void CommitText(Point at)
    {
        var (x, y) = ToPdf(at);
        var win = Window.GetWindow(this);
        string? text = InputDialog.Prompt(win!, "插入文字", "文字内容：", "");
        if (string.IsNullOrEmpty(text)) return;
        Controller!.CommitInsertText(_host.PageIndex, x, y, text, 14);
    }

    private void CommitImage(Point at)
    {
        if (Controller!.PendingImageBgra == null) return;
        var (x, yTop) = ToPdf(at);
        // Scale image to a reasonable default width (180pt), keep aspect.
        double aspect = Controller.PendingImageH / (double)Controller.PendingImageW;
        double wPt = 180, hPt = wPt * aspect;
        Controller.CommitInsertImage(_host.PageIndex, x, yTop - hPt, wPt, hPt);
    }
}
