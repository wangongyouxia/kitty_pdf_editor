using System.Windows;
using System.Windows.Controls;

namespace KittyPdf.App;

/// <summary>Minimal modal text/number prompt (WPF has no built-in InputBox).</summary>
public static class InputDialog
{
    public static string? Prompt(Window owner, string title, string label, string initial = "")
    {
        var win = new Window
        {
            Title = title, Width = 380, SizeToContent = SizeToContent.Height,
            WindowStartupLocation = WindowStartupLocation.CenterOwner, Owner = owner,
            ResizeMode = ResizeMode.NoResize,
        };
        var root = new StackPanel { Margin = new Thickness(14) };
        root.Children.Add(new TextBlock { Text = label, Margin = new Thickness(0, 0, 0, 6) });
        var box = new TextBox { Text = initial };
        root.Children.Add(box);
        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 12, 0, 0),
        };
        var ok = new Button { Content = "确定", Width = 72, Margin = new Thickness(0, 0, 8, 0), IsDefault = true };
        var cancel = new Button { Content = "取消", Width = 72, IsCancel = true };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        root.Children.Add(buttons);
        win.Content = root;

        string? result = null;
        ok.Click += (_, _) => { result = box.Text; win.DialogResult = true; };
        box.Loaded += (_, _) => { box.SelectAll(); box.Focus(); };
        return win.ShowDialog() == true ? result : null;
    }

    public static double? PromptNumber(Window owner, string title, string label, double initial)
    {
        string? s = Prompt(owner, title, label, initial.ToString("0.###"));
        if (s == null) return null;
        return double.TryParse(s, out double v) ? v : null;
    }
}

public static class PageRange
{
    /// <summary>
    /// Parse "1,3-5,8" (1-based, inclusive) into sorted 0-based indices,
    /// clamped to [0, pageCount).  "all"/"" → every page.
    /// </summary>
    public static int[] Parse(string spec, int pageCount)
    {
        spec = (spec ?? "").Trim();
        if (spec.Length == 0 || spec.Equals("all", StringComparison.OrdinalIgnoreCase))
            return Enumerable.Range(0, pageCount).ToArray();
        var set = new SortedSet<int>();
        foreach (var part in spec.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            int dash = part.IndexOf('-');
            if (dash >= 0)
            {
                if (int.TryParse(part[..dash], out int a) && int.TryParse(part[(dash + 1)..], out int b))
                    for (int i = Math.Min(a, b); i <= Math.Max(a, b); i++)
                        if (i >= 1 && i <= pageCount) set.Add(i - 1);
            }
            else if (int.TryParse(part, out int n) && n >= 1 && n <= pageCount)
                set.Add(n - 1);
        }
        return set.ToArray();
    }

    /// <summary>
    /// Like <see cref="Parse"/> but preserves the user's order and repeats
    /// (for reordering). "3,1,2" → [2,0,1].
    /// </summary>
    public static int[] ParseOrdered(string spec, int pageCount)
    {
        var order = new List<int>();
        foreach (var part in (spec ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            int dash = part.IndexOf('-');
            if (dash >= 0)
            {
                if (int.TryParse(part[..dash], out int a) && int.TryParse(part[(dash + 1)..], out int b))
                {
                    int step = a <= b ? 1 : -1;
                    for (int i = a; ; i += step)
                    {
                        if (i >= 1 && i <= pageCount) order.Add(i - 1);
                        if (i == b) break;
                    }
                }
            }
            else if (int.TryParse(part, out int n) && n >= 1 && n <= pageCount)
                order.Add(n - 1);
        }
        return order.ToArray();
    }
}
