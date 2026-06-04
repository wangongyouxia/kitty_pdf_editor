using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>
/// One page in the scroll list: a white "paper" border holding the
/// rendered bitmap plus an overlay <see cref="Canvas"/> the edit mode
/// draws element adorners on.  Rendering is lazy — the host sizes itself
/// from the page's point dimensions immediately (so scrollbars are
/// correct) but only rasterises when <see cref="Render"/> is called for
/// a page that's actually on screen.
/// </summary>
public sealed class PageHost : Border
{
    private readonly PdfSession _session;
    private readonly Image _image;
    public Canvas Overlay { get; }
    public DrawingLayer Draw { get; }
    public int PageIndex { get; }

    public double PageWidthPt { get; }
    public double PageHeightPt { get; }

    public double Zoom { get; private set; } = 1.0;
    private bool _rendered;

    public PageHost(PdfSession session, int pageIndex)
    {
        _session = session;
        PageIndex = pageIndex;
        (PageWidthPt, PageHeightPt) = session.Document.GetPageSize(pageIndex);

        Background = Brushes.White;
        BorderBrush = new SolidColorBrush(Color.FromRgb(0xCC, 0xCC, 0xCC));
        BorderThickness = new Thickness(1);
        Margin = new Thickness(0, 0, 0, 16);
        HorizontalAlignment = HorizontalAlignment.Center;
        Effect = new System.Windows.Media.Effects.DropShadowEffect
        {
            BlurRadius = 12, ShadowDepth = 0, Opacity = 0.25, Color = Colors.Black,
        };

        var grid = new Grid();
        _image = new Image
        {
            Stretch = Stretch.Fill,
            SnapsToDevicePixels = true,
        };
        RenderOptions.SetBitmapScalingMode(_image, BitmapScalingMode.HighQuality);
        Overlay = new Canvas { Background = Brushes.Transparent };
        Draw = new DrawingLayer(this) { IsHitTestVisible = false };
        Panel.SetZIndex(Draw, 50000);
        Overlay.Children.Add(Draw);
        grid.Children.Add(_image);
        grid.Children.Add(Overlay);
        Child = grid;

        ApplyZoom(1.0);
    }

    public void ApplyZoom(double zoom)
    {
        Zoom = zoom;
        Width = PageWidthPt * zoom;
        Height = PageHeightPt * zoom;
        Draw.Width = Width;
        Draw.Height = Height;
        _rendered = false;
        _image.Source = null;
    }

    /// <summary>Rasterise the page now (no-op if already rendered at this zoom).</summary>
    public void Render()
    {
        if (_rendered) return;
        double dpiScale = 1.0;
        var src = PresentationSource.FromVisual(this);
        if (src?.CompositionTarget != null)
            dpiScale = src.CompositionTarget.TransformToDevice.M11;

        double renderScale = Zoom * dpiScale;
        var rp = _session.Document.RenderPage(PageIndex, renderScale);
        var bmp = BitmapSource.Create(
            rp.WidthPx, rp.HeightPx,
            96 * dpiScale, 96 * dpiScale,
            PixelFormats.Bgra32, null, rp.Pixels, rp.Stride);
        bmp.Freeze();
        _image.Source = bmp;
        _rendered = true;
    }

    /// <summary>Free the bitmap (page scrolled far off screen).</summary>
    public void Unrender()
    {
        if (!_rendered) return;
        _image.Source = null;
        _rendered = false;
    }

    /// <summary>Force a re-render on next <see cref="Render"/> (after an edit).</summary>
    public void Invalidate() { _rendered = false; _image.Source = null; }
}
