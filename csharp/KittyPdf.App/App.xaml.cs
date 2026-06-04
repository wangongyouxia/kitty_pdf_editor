using System.IO;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using KittyPdf.Core;

namespace KittyPdf.App;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // Crash logging so headless launch verification can detect faults.
        DispatcherUnhandledException += (_, args) =>
        {
            try
            {
                File.WriteAllText(
                    Path.Combine(Path.GetTempPath(), "kitty_crash.log"),
                    args.Exception.ToString());
            }
            catch { /* ignore */ }
        };

        // Headless helper used for automated verification (renders a
        // page to PNG through the exact WPF bitmap pipeline, then exits):
        //   --render <pdf> <out.png> [pageIndex] [scale]
        if (e.Args.Length >= 3 && e.Args[0] == "--render")
        {
            int pg = e.Args.Length >= 4 ? int.Parse(e.Args[3]) : 0;
            double scale = e.Args.Length >= 5 ? double.Parse(e.Args[4]) : 2.0;
            RunRender(e.Args[1], e.Args[2], pg, scale);
            Shutdown();
            return;
        }

        if (e.Args.Length >= 3 && e.Args[0] == "--shot")
        {
            var w = new MainWindow { Width = 1180, Height = 820 };
            w.Show();
            w.OpenPath(e.Args[1]);
            // Let layout + lazy render settle, then snapshot the window.
            var timer = new System.Windows.Threading.DispatcherTimer
            { Interval = TimeSpan.FromMilliseconds(1200) };
            timer.Tick += (_, _) =>
            {
                timer.Stop();
                try
                {
                    int pw = (int)w.ActualWidth, ph = (int)w.ActualHeight;
                    var rtb = new RenderTargetBitmap(pw, ph, 96, 96, PixelFormats.Pbgra32);
                    rtb.Render(w);
                    var enc = new PngBitmapEncoder();
                    enc.Frames.Add(BitmapFrame.Create(rtb));
                    using var fs = File.Create(e.Args[2]);
                    enc.Save(fs);
                }
                catch { /* ignore */ }
                Shutdown();
            };
            timer.Start();
            return;
        }

        var win = new MainWindow();
        win.Show();
        if (e.Args.Length == 1 && File.Exists(e.Args[0]))
            win.OpenPath(e.Args[0]);
    }

    private static void RunRender(string pdf, string outPng, int pg, double scale)
    {
        using var d = PdfDocument.Open(pdf);
        var rp = d.RenderPage(pg, scale);
        var bmp = BitmapSource.Create(rp.WidthPx, rp.HeightPx, 96, 96,
            System.Windows.Media.PixelFormats.Bgra32, null, rp.Pixels, rp.Stride);
        var enc = new PngBitmapEncoder();
        enc.Frames.Add(BitmapFrame.Create(bmp));
        using var fs = File.Create(outPng);
        enc.Save(fs);
        Console.WriteLine($"wrote {outPng} ({rp.WidthPx}x{rp.HeightPx})");
    }
}
