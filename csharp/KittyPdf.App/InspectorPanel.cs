using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>
/// Right-hand properties panel.  Shows the *engine-read* attributes of
/// the selected element — crucially the real font name + weight + bold
/// flag straight from PDFium, so the user can see that editing never
/// silently changes the style.
/// </summary>
public sealed class InspectorPanel : Border
{
    private readonly TextBlock _title = new() { FontWeight = FontWeights.Bold, FontSize = 14,
        Foreground = new SolidColorBrush(Color.FromRgb(0, 90, 180)), Margin = new Thickness(0, 0, 0, 8) };
    private readonly TextBox _text = new() { AcceptsReturn = true, TextWrapping = TextWrapping.Wrap,
        MinHeight = 80, MaxHeight = 160, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
    private readonly TextBlock _font = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _style = new();
    private readonly TextBlock _size = new();
    private readonly TextBlock _pos = new() { FontFamily = new FontFamily("Consolas"), Foreground = Brushes.Gray };
    private readonly Button _apply = new() { Content = "应用文字", Margin = new Thickness(0, 8, 0, 4), Padding = new Thickness(8, 4, 8, 4) };
    private readonly Button _delete = new() { Content = "删除元素", Foreground = Brushes.IndianRed, Padding = new Thickness(8, 4, 8, 4) };
    private readonly StackPanel _textControls = new();
    private readonly TextBlock _hint = new() { TextWrapping = TextWrapping.Wrap, Foreground = Brushes.Gray,
        Text = "进入编辑模式后点击页面上的元素查看属性。\n移动 / 缩放 / 改字都不会改变原字体。" };

    private EditController? _ctrl;
    private ElementAdorner? _current;

    public InspectorPanel()
    {
        Width = 268;
        Background = new SolidColorBrush(Color.FromRgb(0xFA, 0xFA, 0xFA));
        BorderBrush = new SolidColorBrush(Color.FromRgb(0xDD, 0xDD, 0xDD));
        BorderThickness = new Thickness(1, 0, 0, 0);
        Padding = new Thickness(12);

        var root = new StackPanel();
        root.Children.Add(_title);
        root.Children.Add(_hint);

        _textControls.Children.Add(Label("文字内容"));
        _textControls.Children.Add(_text);
        _textControls.Children.Add(_apply);
        _textControls.Children.Add(Sep());
        _textControls.Children.Add(Label("字体（来自引擎，原样保留）"));
        _textControls.Children.Add(_font);
        _textControls.Children.Add(_style);
        _textControls.Children.Add(_size);
        _textControls.Children.Add(Sep());
        _textControls.Children.Add(Label("位置 (PDF 点)"));
        _textControls.Children.Add(_pos);
        _textControls.Children.Add(Sep());
        _textControls.Children.Add(_delete);
        _textControls.Visibility = Visibility.Collapsed;
        root.Children.Add(_textControls);

        Child = root;

        _apply.Click += (_, _) =>
        {
            if (_ctrl != null && _current != null)
                _ctrl.CommitText(_current, _text.Text);
        };
        _delete.Click += (_, _) =>
        {
            if (_ctrl != null && _current != null)
                _ctrl.CommitDelete(_current);
        };
    }

    public void Attach(EditController ctrl) => _ctrl = ctrl;

    private static TextBlock Label(string t) => new()
    {
        Text = t, FontSize = 11, Foreground = Brushes.Gray, Margin = new Thickness(0, 6, 0, 2),
    };
    private static Border Sep() => new()
    {
        Height = 1, Background = new SolidColorBrush(Color.FromRgb(0xE5, 0xE5, 0xE5)),
        Margin = new Thickness(0, 8, 0, 0),
    };

    public void ShowNone()
    {
        _current = null;
        _title.Text = "元素";
        _hint.Visibility = Visibility.Visible;
        _textControls.Visibility = Visibility.Collapsed;
    }

    public void Show(ElementAdorner adorner)
    {
        _current = adorner;
        var el = adorner.Element;
        _hint.Visibility = Visibility.Collapsed;
        _textControls.Visibility = Visibility.Visible;

        if (el.Kind == PdfElementKind.Text)
        {
            _title.Text = "文字段";
            _text.IsEnabled = true;
            _apply.IsEnabled = true;
            _text.Text = el.Text ?? "";
            _font.Text = "字体：" + (el.FontName ?? "（未知）");
            var s = new List<string>();
            if (el.IsBold) s.Add("粗体");
            if (el.IsItalic) s.Add("斜体");
            if (el.FontWeight > 0) s.Add($"weight {el.FontWeight}");
            _style.Text = "样式：" + (s.Count > 0 ? string.Join("、", s) : "常规");
            _size.Text = $"字号：{el.FontSize:0.#} pt";
        }
        else
        {
            _title.Text = el.Kind == PdfElementKind.Image ? "图片" : el.Kind.ToString();
            _text.Text = "";
            _text.IsEnabled = false;
            _apply.IsEnabled = false;
            _font.Text = "";
            _style.Text = "";
            _size.Text = "";
        }
        _pos.Text = $"({el.Left:0.#}, {el.Bottom:0.#}) → ({el.Right:0.#}, {el.Top:0.#})";
    }
}
