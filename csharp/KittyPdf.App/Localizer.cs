using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;

namespace KittyPdf.App;

/// <summary>
/// Lightweight UI localisation: a tree-walker that swaps the chrome text
/// (menus + toolbars) between Chinese and English, mirroring the Python
/// build's apply_language() approach.  Matches on current text via a
/// bidirectional map, so toggling is reversible.
/// </summary>
public static class Localizer
{
    private static readonly Dictionary<string, string> ZhToEn = new()
    {
        // menus
        ["文件(_F)"] = "File(_F)", ["编辑(_E)"] = "Edit(_E)", ["页面(_P)"] = "Page(_P)",
        ["文档(_D)"] = "Document(_D)", ["工具(_T)"] = "Tools(_T)", ["导出(_X)"] = "Export(_X)",
        ["帮助(_H)"] = "Help(_H)",
        // file
        ["打开…"] = "Open…", ["保存"] = "Save", ["另存为…"] = "Save As…", ["退出"] = "Exit",
        // edit
        ["撤销"] = "Undo", ["重做"] = "Redo", ["内容编辑模式"] = "Edit Content Mode",
        // page
        ["插入空白页…"] = "Insert Blank Page…", ["删除页面…"] = "Delete Pages…",
        ["复制页面…"] = "Duplicate Pages…", ["向左旋转 90°"] = "Rotate Left 90°",
        ["向右旋转 90°"] = "Rotate Right 90°", ["提取页面…"] = "Extract Pages…",
        ["重排页面…"] = "Reorder Pages…",
        // document
        ["合并 PDF…"] = "Merge PDFs…", ["拆分 PDF…"] = "Split PDF…",
        ["添加文字水印…"] = "Add Text Watermark…", ["添加页码…"] = "Add Page Numbers…",
        ["加密（设置密码）…"] = "Encrypt…", ["移除密码…"] = "Remove Password…",
        ["文档属性…"] = "Document Properties…",
        // tools / export / help
        ["搜索…"] = "Search…", ["导出文本…"] = "Export Text…",
        ["导出每页图片…"] = "Export Page Images…", ["关于"] = "About", ["赞赏支持"] = "Donate",
        // toolbar row 1
        ["打开"] = "Open", ["另存为"] = "Save As", ["✏ 编辑内容"] = "✏ Edit", ["适合宽度"] = "Fit Width",
        ["❤ 赞赏"] = "❤ Donate",
        // tool strip
        ["选择"] = "Select", ["▭ 矩形"] = "▭ Rect", ["◯ 椭圆"] = "◯ Ellipse", ["／ 直线"] = "／ Line",
        ["➜ 箭头"] = "➜ Arrow", ["▥ 高亮"] = "▥ Highlight", ["✎ 画笔"] = "✎ Pen", ["🅣 文字"] = "🅣 Text",
        ["🖼 图片"] = "🖼 Image", ["✍ 签名"] = "✍ Sign", ["颜色"] = "Color", ["粗细"] = "Width",
        // language toggle item
        ["English"] = "中文",
    };

    private static readonly Dictionary<string, string> EnToZh = Invert(ZhToEn);

    private static Dictionary<string, string> Invert(Dictionary<string, string> m)
    {
        var d = new Dictionary<string, string>();
        foreach (var kv in m) d[kv.Value] = kv.Key;
        return d;
    }

    public static void Apply(DependencyObject root, bool english)
    {
        var map = english ? ZhToEn : EnToZh;
        Walk(root, map);
    }

    private static void Walk(DependencyObject obj, Dictionary<string, string> map)
    {
        foreach (var child in LogicalTreeHelper.GetChildren(obj))
        {
            if (child is DependencyObject d)
            {
                Translate(d, map);
                Walk(d, map);
            }
        }
    }

    private static void Translate(DependencyObject d, Dictionary<string, string> map)
    {
        switch (d)
        {
            case MenuItem mi when mi.Header is string h && map.TryGetValue(h, out var t):
                mi.Header = t; break;
            case TextBlock tb when map.TryGetValue(tb.Text, out var t):
                tb.Text = t; break;
            // RadioButton / ToggleButton / Button all derive from ContentControl
            case ContentControl cc when cc.Content is string s && map.TryGetValue(s, out var t):
                cc.Content = t; break;
        }
    }
}
