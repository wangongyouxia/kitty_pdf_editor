using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace KittyPdf.App;

/// <summary>Thank-you / donate dialog showing the bundled QR image.</summary>
public sealed class DonateWindow : Window
{
    public DonateWindow()
    {
        Title = "赞赏支持";
        SizeToContent = SizeToContent.WidthAndHeight;
        ResizeMode = ResizeMode.NoResize;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        var panel = new StackPanel { Margin = new Thickness(20) };
        panel.Children.Add(new TextBlock
        {
            Text = "如果这个工具帮到你，欢迎请作者喝杯咖啡 🐱",
            FontSize = 14, Margin = new Thickness(0, 0, 0, 12),
            HorizontalAlignment = HorizontalAlignment.Center,
        });
        try
        {
            var img = new Image
            {
                Source = new BitmapImage(new Uri("pack://application:,,,/donate.png")),
                Width = 280, Stretch = Stretch.Uniform,
            };
            panel.Children.Add(img);
        }
        catch
        {
            panel.Children.Add(new TextBlock { Text = "(二维码图片缺失)", Foreground = Brushes.Gray });
        }
        Content = panel;
    }
}
