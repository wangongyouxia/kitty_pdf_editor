using System.Windows;
using System.Windows.Controls;
using System.Windows.Ink;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace KittyPdf.App;

/// <summary>Draw a signature with an InkCanvas; returns a BGRA bitmap.</summary>
public sealed class SignatureWindow : Window
{
    private readonly InkCanvas _ink;
    public byte[]? ResultBgra { get; private set; }
    public int ResultW { get; private set; }
    public int ResultH { get; private set; }

    public SignatureWindow()
    {
        Title = "手写签名";
        Width = 560; Height = 320;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;

        var root = new DockPanel { LastChildFill = true };
        var bar = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(8) };
        DockPanel.SetDock(bar, Dock.Bottom);
        var clear = new Button { Content = "清除", Width = 72, Margin = new Thickness(0, 0, 8, 0) };
        var ok = new Button { Content = "确定", Width = 72, Margin = new Thickness(0, 0, 8, 0), IsDefault = true };
        var cancel = new Button { Content = "取消", Width = 72, IsCancel = true };
        bar.Children.Add(clear); bar.Children.Add(ok); bar.Children.Add(cancel);

        _ink = new InkCanvas { Background = Brushes.White };
        _ink.DefaultDrawingAttributes = new DrawingAttributes
        { Color = Colors.Black, Width = 3, Height = 3, FitToCurve = true };

        root.Children.Add(bar);
        var hint = new TextBlock { Text = "在白色区域用鼠标书写签名", Margin = new Thickness(8, 4, 8, 4),
            Foreground = Brushes.Gray };
        DockPanel.SetDock(hint, Dock.Top);
        root.Children.Add(hint);
        root.Children.Add(_ink);
        Content = root;

        clear.Click += (_, _) => _ink.Strokes.Clear();
        ok.Click += (_, _) => { Capture(); DialogResult = true; };
    }

    private void Capture()
    {
        if (_ink.Strokes.Count == 0) { ResultBgra = null; return; }
        var bounds = _ink.Strokes.GetBounds();
        if (bounds.IsEmpty || bounds.Width < 1 || bounds.Height < 1) return;

        // Render the strokes to a transparent BGRA bitmap, scaled up 2x.
        const double scale = 2.0;
        int w = (int)Math.Ceiling(bounds.Width * scale);
        int h = (int)Math.Ceiling(bounds.Height * scale);
        var visual = new DrawingVisual();
        using (var dc = visual.RenderOpen())
        {
            dc.PushTransform(new ScaleTransform(scale, scale));
            dc.PushTransform(new TranslateTransform(-bounds.X, -bounds.Y));
            foreach (var s in _ink.Strokes) s.Draw(dc);
        }
        var rtb = new RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32);
        rtb.Render(visual);
        var conv = new FormatConvertedBitmap(rtb, PixelFormats.Bgra32, null, 0);
        int stride = w * 4;
        var px = new byte[stride * h];
        conv.CopyPixels(px, stride, 0);
        ResultBgra = px; ResultW = w; ResultH = h;
    }
}
