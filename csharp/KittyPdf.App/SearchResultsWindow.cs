using System.Windows;
using System.Windows.Controls;
using KittyPdf.Core;

namespace KittyPdf.App;

/// <summary>Non-modal list of search hits; activating one jumps to its page.</summary>
public sealed class SearchResultsWindow : Window
{
    public SearchResultsWindow(IReadOnlyList<PdfDocument.SearchHit> hits, Action<int> goToPage)
    {
        Title = $"搜索结果（{hits.Count}）";
        Width = 420;
        Height = 480;
        WindowStartupLocation = WindowStartupLocation.CenterOwner;

        var list = new ListBox { Margin = new Thickness(8) };
        foreach (var h in hits)
            list.Items.Add(new ListBoxItem
            {
                Content = $"第 {h.Page + 1} 页:  …{h.Snippet}…",
                Tag = h.Page,
            });
        list.MouseDoubleClick += (_, _) =>
        {
            if (list.SelectedItem is ListBoxItem it && it.Tag is int page)
                goToPage(page);
        };
        list.SelectionChanged += (_, _) =>
        {
            if (list.SelectedItem is ListBoxItem it && it.Tag is int page)
                goToPage(page);
        };
        Content = list;
    }
}
