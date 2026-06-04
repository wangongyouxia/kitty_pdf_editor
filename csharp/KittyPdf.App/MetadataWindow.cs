using System.Windows;
using System.Windows.Controls;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>Edit document Info dictionary fields.</summary>
public sealed class MetadataWindow : Window
{
    private readonly TextBox _title = new();
    private readonly TextBox _author = new();
    private readonly TextBox _subject = new();
    private readonly TextBox _keywords = new();
    private readonly TextBox _creator = new();

    public PdfSharpOps.DocInfo Result { get; private set; }

    public MetadataWindow(PdfSharpOps.DocInfo info)
    {
        Title = "文档属性";
        Width = 440; SizeToContent = SizeToContent.Height;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;
        ResizeMode = ResizeMode.NoResize;
        Result = info;

        _title.Text = info.Title; _author.Text = info.Author;
        _subject.Text = info.Subject; _keywords.Text = info.Keywords;
        _creator.Text = info.Creator;

        var grid = new Grid { Margin = new Thickness(14) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        void Row(string label, TextBox box)
        {
            int r = grid.RowDefinitions.Count;
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var t = new TextBlock { Text = label, Margin = new Thickness(0, 6, 10, 6), VerticalAlignment = VerticalAlignment.Center };
            Grid.SetRow(t, r); Grid.SetColumn(t, 0);
            box.Margin = new Thickness(0, 4, 0, 4);
            Grid.SetRow(box, r); Grid.SetColumn(box, 1);
            grid.Children.Add(t); grid.Children.Add(box);
        }
        Row("标题", _title); Row("作者", _author); Row("主题", _subject);
        Row("关键字", _keywords); Row("创建程序", _creator);

        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var ok = new Button { Content = "确定", Width = 72, Margin = new Thickness(0, 0, 8, 0), IsDefault = true };
        var cancel = new Button { Content = "取消", Width = 72, IsCancel = true };
        buttons.Children.Add(ok); buttons.Children.Add(cancel);
        int br = grid.RowDefinitions.Count;
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetRow(buttons, br); Grid.SetColumn(buttons, 1);
        buttons.Margin = new Thickness(0, 12, 0, 0);
        grid.Children.Add(buttons);

        ok.Click += (_, _) =>
        {
            Result = new PdfSharpOps.DocInfo(_title.Text, _author.Text, _subject.Text, _keywords.Text, _creator.Text);
            DialogResult = true;
        };
        Content = grid;
    }
}
