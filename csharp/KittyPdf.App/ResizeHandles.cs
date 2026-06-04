using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace KittyPdf.App;

/// <summary>
/// Eight resize handles around the selected adorner, drawn on the page
/// overlay.  Dragging a handle resizes the adorner box live; on release
/// the controller commits a scale+translate (font preserved).
/// </summary>
public sealed class ResizeHandles
{
    private static readonly string[] Pos = { "nw", "n", "ne", "e", "se", "s", "sw", "w" };
    private static readonly Dictionary<string, Cursor> Cursors = new()
    {
        ["nw"] = System.Windows.Input.Cursors.SizeNWSE, ["se"] = System.Windows.Input.Cursors.SizeNWSE,
        ["ne"] = System.Windows.Input.Cursors.SizeNESW, ["sw"] = System.Windows.Input.Cursors.SizeNESW,
        ["n"] = System.Windows.Input.Cursors.SizeNS, ["s"] = System.Windows.Input.Cursors.SizeNS,
        ["e"] = System.Windows.Input.Cursors.SizeWE, ["w"] = System.Windows.Input.Cursors.SizeWE,
    };

    private readonly EditController _ctrl;
    private readonly PageHost _host;
    private readonly ElementAdorner _adorner;
    private readonly List<Thumb> _thumbs = new();

    private double _l, _t, _w, _h;       // working geometry during a drag
    private double _dxAcc, _dyAcc;

    public ResizeHandles(EditController ctrl, PageHost host, ElementAdorner adorner)
    {
        _ctrl = ctrl;
        _host = host;
        _adorner = adorner;
        foreach (var p in Pos)
        {
            var th = MakeThumb(p);
            _thumbs.Add(th);
            host.Overlay.Children.Add(th);
            Panel.SetZIndex(th, 60000);
        }
        Reposition();
    }

    private Thumb MakeThumb(string which)
    {
        var th = new Thumb { Width = 9, Height = 9, Cursor = Cursors[which], Tag = which };
        var rect = new FrameworkElementFactory(typeof(Rectangle));
        rect.SetValue(Shape.FillProperty, Brushes.White);
        rect.SetValue(Shape.StrokeProperty, new SolidColorBrush(Color.FromRgb(0, 120, 215)));
        rect.SetValue(Shape.StrokeThicknessProperty, 1.0);
        th.Template = new ControlTemplate(typeof(Thumb)) { VisualTree = rect };

        th.DragStarted += (_, _) =>
        {
            _l = Canvas.GetLeft(_adorner);
            _t = Canvas.GetTop(_adorner);
            _w = _adorner.Width;
            _h = _adorner.Height;
            _dxAcc = _dyAcc = 0;
        };
        th.DragDelta += (_, e) =>
        {
            _dxAcc += e.HorizontalChange;
            _dyAcc += e.VerticalChange;
            double l = _l, t = _t, w = _w, h = _h;
            if (which.Contains('w')) { l = _l + _dxAcc; w = _w - _dxAcc; }
            if (which.Contains('e')) { w = _w + _dxAcc; }
            if (which.Contains('n')) { t = _t + _dyAcc; h = _h - _dyAcc; }
            if (which.Contains('s')) { h = _h + _dyAcc; }
            if (w < 4) { w = 4; } if (h < 4) { h = 4; }
            Canvas.SetLeft(_adorner, l);
            Canvas.SetTop(_adorner, t);
            _adorner.Width = w;
            _adorner.Height = h;
            Reposition();
        };
        th.DragCompleted += (_, _) =>
        {
            _ctrl.CommitResize(_adorner,
                Canvas.GetLeft(_adorner), Canvas.GetTop(_adorner),
                _adorner.Width, _adorner.Height);
        };
        return th;
    }

    public void Reposition()
    {
        double l = Canvas.GetLeft(_adorner), t = Canvas.GetTop(_adorner);
        double w = _adorner.Width, h = _adorner.Height;
        var coords = new Dictionary<string, (double x, double y)>
        {
            ["nw"] = (l, t), ["n"] = (l + w / 2, t), ["ne"] = (l + w, t),
            ["e"] = (l + w, t + h / 2), ["se"] = (l + w, t + h),
            ["s"] = (l + w / 2, t + h), ["sw"] = (l, t + h), ["w"] = (l, t + h / 2),
        };
        foreach (var th in _thumbs)
        {
            var (x, y) = coords[(string)th.Tag];
            Canvas.SetLeft(th, x - th.Width / 2);
            Canvas.SetTop(th, y - th.Height / 2);
        }
    }

    public void Dispose()
    {
        foreach (var th in _thumbs)
            if (th.Parent is Panel p) p.Children.Remove(th);
            else _host.Overlay.Children.Remove(th);
        _thumbs.Clear();
    }
}
