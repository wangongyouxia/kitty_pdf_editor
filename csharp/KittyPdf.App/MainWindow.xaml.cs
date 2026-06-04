using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using KittyPdf.Core;
using Microsoft.Win32;

namespace KittyPdf.App;

public partial class MainWindow : Window
{
    private readonly PdfSession _session = new();
    private readonly List<PageHost> _hosts = new();
    private double _zoom = 1.0;
    private int _currentPage;
    private EditController? _edit;

    public MainWindow()
    {
        InitializeComponent();
        InitToolStrip();
        _session.Changed += OnDocumentChanged;
        _session.DirtyChanged += _ => UpdateTitle();
        UpdateCommandStates();
    }

    // ------------------------------------------------------------------
    // Open / Save
    // ------------------------------------------------------------------
    private void OnOpen(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog { Filter = "PDF 文件 (*.pdf)|*.pdf|所有文件 (*.*)|*.*" };
        if (dlg.ShowDialog(this) != true) return;
        try
        {
            _session.Open(dlg.FileName);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, "打开失败：" + ex.Message, "Kitty PDF",
                MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    public void OpenPath(string path)
    {
        try { _session.Open(path); }
        catch
        {
            // Likely password-protected — prompt and retry.
            string? pw = InputDialog.Prompt(this, "需要密码", "该 PDF 已加密，请输入密码：", "");
            if (pw == null) return;
            try { _session.Open(path, pw); }
            catch (Exception ex) { ShowError("打开失败：" + ex.Message); }
        }
    }

    private void OnSave(object sender, RoutedEventArgs e)
    {
        if (!_session.IsOpen) return;
        if (_session.Path == null) { OnSaveAs(sender, e); return; }
        try { _session.Save(); UpdateTitle(); }
        catch (Exception ex) { ShowError("保存失败：" + ex.Message); }
    }

    private void OnSaveAs(object sender, RoutedEventArgs e)
    {
        if (!_session.IsOpen) return;
        var dlg = new SaveFileDialog
        {
            Filter = "PDF 文件 (*.pdf)|*.pdf",
            FileName = _session.Path != null ? Path.GetFileName(_session.Path) : "未命名.pdf",
        };
        if (dlg.ShowDialog(this) != true) return;
        try { _session.Save(dlg.FileName); UpdateTitle(); }
        catch (Exception ex) { ShowError("保存失败：" + ex.Message); }
    }

    private void OnUndo(object sender, RoutedEventArgs e) { _session.Undo(); }
    private void OnRedo(object sender, RoutedEventArgs e) { _session.Redo(); }

    // ------------------------------------------------------------------
    // Document lifecycle → (re)build page hosts
    // ------------------------------------------------------------------
    private void OnDocumentChanged()
    {
        _edit?.Clear();
        PagesPanel.Children.Clear();
        _hosts.Clear();

        if (_session.IsOpen)
        {
            for (int i = 0; i < _session.PageCount; i++)
            {
                var host = new PageHost(_session, i);
                _hosts.Add(host);
                PagesPanel.Children.Add(host);
            }
            ApplyZoomToHosts();
            Dispatcher.BeginInvoke(new Action(RenderVisible),
                System.Windows.Threading.DispatcherPriority.Loaded);

            // Auto-enter edit mode (matches the Python build's default).
            if (_edit == null) _edit = new EditController(this, _session);
            _edit.Rebuild(_hosts);
            if (BtnEdit.IsChecked != true) BtnEdit.IsChecked = true;
            MenuEdit.IsChecked = true;
            _edit.SetActive(true);
        }
        UpdateTitle();
        UpdateCommandStates();
    }

    // ------------------------------------------------------------------
    // Zoom
    // ------------------------------------------------------------------
    private void OnZoomIn(object sender, RoutedEventArgs e) => SetZoom(_zoom * 1.2);
    private void OnZoomOut(object sender, RoutedEventArgs e) => SetZoom(_zoom / 1.2);

    private void OnFitWidth(object sender, RoutedEventArgs e)
    {
        if (_hosts.Count == 0) return;
        double avail = Scroller.ViewportWidth - 60;
        if (avail <= 0) return;
        SetZoom(avail / _hosts[0].PageWidthPt);
    }

    private void SetZoom(double zoom)
    {
        _zoom = Math.Clamp(zoom, 0.1, 8.0);
        ZoomLabel.Text = $"{_zoom * 100:0}%";
        ApplyZoomToHosts();
        _edit?.OnZoomChanged();
        RenderVisible();
    }

    private void ApplyZoomToHosts()
    {
        foreach (var h in _hosts) h.ApplyZoom(_zoom);
    }

    // ------------------------------------------------------------------
    // Lazy render: only pages intersecting the viewport (+margin).
    // ------------------------------------------------------------------
    private void OnScrollChanged(object sender, ScrollChangedEventArgs e) => RenderVisible();

    private void RenderVisible()
    {
        if (_hosts.Count == 0) return;
        double top = Scroller.VerticalOffset - 400;
        double bottom = Scroller.VerticalOffset + Scroller.ViewportHeight + 400;

        double bestDist = double.MaxValue;
        foreach (var h in _hosts)
        {
            GeneralTransform t;
            try { t = h.TransformToAncestor(PagesPanel); }
            catch { continue; }
            var pos = t.Transform(new Point(0, 0));
            double hTop = pos.Y;
            double hBottom = pos.Y + h.Height;
            bool visible = hBottom >= top && hTop <= bottom;
            if (visible)
            {
                h.Render();
                _edit?.EnsureOverlay(h);
            }
            else
            {
                h.Unrender();
            }
            double dist = Math.Abs(hTop - Scroller.VerticalOffset);
            if (dist < bestDist) { bestDist = dist; _currentPage = h.PageIndex; }
        }
    }

    // ------------------------------------------------------------------
    // Edit mode toggle
    // ------------------------------------------------------------------
    private void OnToggleEdit(object sender, RoutedEventArgs e)
    {
        if (!_session.IsOpen) { BtnEdit.IsChecked = false; MenuEdit.IsChecked = false; return; }
        _edit ??= new EditController(this, _session);
        _edit.Rebuild(_hosts);
        MenuEdit.IsChecked = BtnEdit.IsChecked == true;
        _edit.SetActive(BtnEdit.IsChecked == true);
        RenderVisible();
    }

    // ------------------------------------------------------------------
    public void RefreshPage(int pageIndex)
    {
        if (pageIndex < 0 || pageIndex >= _hosts.Count) return;
        _hosts[pageIndex].Invalidate();
        _hosts[pageIndex].Render();
        _edit?.RebuildPage(_hosts[pageIndex]);
        UpdateCommandStates();
        UpdateTitle();
    }

    public ContentControl InspectorSlot => InspectorHost;

    /// <summary>Test hook for --shot: select the first element on page 0.</summary>
    public bool SelectFirstForShot()
    {
        if (_edit == null || _hosts.Count == 0) return false;
        return _edit.SelectFirst(_hosts[0]);
    }

    // ------------------------------------------------------------------
    // Drawing tools
    // ------------------------------------------------------------------
    private static readonly (string name, Color color)[] StrokeColors =
    {
        ("红", Colors.Red), ("黑", Colors.Black), ("蓝", Colors.Blue),
        ("绿", Color.FromRgb(0, 150, 0)), ("黄", Color.FromRgb(255, 210, 0)),
        ("橙", Colors.Orange),
    };

    private void InitToolStrip()
    {
        foreach (var (name, _) in StrokeColors) StrokeColorBox.Items.Add(name);
        StrokeColorBox.SelectedIndex = 0;
        foreach (var w in new[] { "1", "2", "3", "5", "8" }) StrokeWidthBox.Items.Add(w);
        StrokeWidthBox.SelectedIndex = 1;
    }

    private void EnsureEditActive()
    {
        if (_edit == null) _edit = new EditController(this, _session);
        if (!_edit.IsActive)
        {
            _edit.Rebuild(_hosts);
            BtnEdit.IsChecked = true;
            MenuEdit.IsChecked = true;
            _edit.SetActive(true);
            RenderVisible();
        }
    }

    private void OnToolPick(object sender, RoutedEventArgs e)
    {
        if (sender is not RadioButton rb || rb.Tag is not string tag) return;
        if (!_session.IsOpen) { ToolSelect.IsChecked = true; return; }
        EnsureEditActive();
        if (Enum.TryParse<DrawTool>(tag, out var tool))
            _edit!.SetTool(tool);
    }

    private void OnStrokeColorChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_edit != null && StrokeColorBox.SelectedIndex >= 0)
            _edit.StrokeColor = StrokeColors[StrokeColorBox.SelectedIndex].color;
    }

    private void OnStrokeWidthChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_edit != null && StrokeWidthBox.SelectedItem is string s && double.TryParse(s, out double w))
            _edit.StrokeWidth = w;
    }

    private void OnInsertImage(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        var dlg = new OpenFileDialog { Filter = "图片 (*.png;*.jpg;*.jpeg;*.bmp)|*.png;*.jpg;*.jpeg;*.bmp" };
        if (dlg.ShowDialog(this) != true) return;
        if (!LoadImageAsPending(dlg.FileName)) { ShowError("无法读取图片。"); return; }
        EnsureEditActive();
        _edit!.SetTool(DrawTool.Image);
        MessageBox.Show(this, "在页面上点击以放置图片。", "插入图片");
    }

    private void OnSignature(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        var win = new SignatureWindow { Owner = this };
        if (win.ShowDialog() != true || win.ResultBgra == null) return;
        _edit ??= new EditController(this, _session);
        _edit.PendingImageBgra = win.ResultBgra;
        _edit.PendingImageW = win.ResultW;
        _edit.PendingImageH = win.ResultH;
        EnsureEditActive();
        _edit.SetTool(DrawTool.Image);
        MessageBox.Show(this, "在页面上点击以放置签名。", "签名");
    }

    private bool LoadImageAsPending(string path)
    {
        try
        {
            var bmp = new System.Windows.Media.Imaging.BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = System.Windows.Media.Imaging.BitmapCacheOption.OnLoad;
            bmp.UriSource = new Uri(path);
            bmp.EndInit();
            var conv = new System.Windows.Media.Imaging.FormatConvertedBitmap(
                bmp, System.Windows.Media.PixelFormats.Bgra32, null, 0);
            int w = conv.PixelWidth, h = conv.PixelHeight, stride = w * 4;
            var px = new byte[stride * h];
            conv.CopyPixels(px, stride, 0);
            _edit ??= new EditController(this, _session);
            _edit.PendingImageBgra = px;
            _edit.PendingImageW = w;
            _edit.PendingImageH = h;
            return true;
        }
        catch { return false; }
    }

    // ------------------------------------------------------------------
    // Menu: misc
    // ------------------------------------------------------------------
    private void OnExit(object sender, RoutedEventArgs e) => Close();

    private void OnToggleEditMenu(object sender, RoutedEventArgs e)
    {
        BtnEdit.IsChecked = MenuEdit.IsChecked;
        OnToggleEdit(sender, e);
    }

    private void OnAbout(object sender, RoutedEventArgs e) =>
        MessageBox.Show(this,
            "Kitty PDF Editor\n\n基于 PDFium 的元素级 PDF 编辑器。\n" +
            "移动 / 改字 / 删除都直接操作页面对象，原字体永不丢失。",
            "关于", MessageBoxButton.OK, MessageBoxImage.Information);

    private void OnDonate(object sender, RoutedEventArgs e)
    {
        var dlg = new DonateWindow { Owner = this };
        dlg.ShowDialog();
    }

    // ------------------------------------------------------------------
    // Menu: page operations
    // ------------------------------------------------------------------
    private bool RequireOpen()
    {
        if (_session.IsOpen) return true;
        MessageBox.Show(this, "请先打开一个 PDF。", "Kitty PDF",
            MessageBoxButton.OK, MessageBoxImage.Information);
        return false;
    }

    private void OnInsertBlank(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        double? w = InputDialog.PromptNumber(this, "插入空白页", "宽度（pt，A4≈595）：", 595);
        if (w == null) return;
        double? h = InputDialog.PromptNumber(this, "插入空白页", "高度（pt，A4≈842）：", 842);
        if (h == null) return;
        int at = _currentPage + 1;
        _session.Mutate(d => d.InsertBlankPage(at, w.Value, h.Value));
    }

    private void OnDeletePages(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? spec = InputDialog.Prompt(this, "删除页面",
            $"页码（如 1,3-5；共 {_session.PageCount} 页）：", (_currentPage + 1).ToString());
        if (spec == null) return;
        var idx = PageRange.Parse(spec, _session.PageCount);
        if (idx.Length == 0) return;
        if (idx.Length >= _session.PageCount)
        {
            MessageBox.Show(this, "不能删除全部页面。", "删除");
            return;
        }
        _session.Mutate(d => d.DeletePages(idx));
    }

    private void OnDuplicatePages(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? spec = InputDialog.Prompt(this, "复制页面",
            $"页码（如 1,3-5；共 {_session.PageCount} 页）：", (_currentPage + 1).ToString());
        if (spec == null) return;
        var idx = PageRange.Parse(spec, _session.PageCount);
        if (idx.Length == 0) return;
        _session.MutateReplace(d => d.DuplicatePagesToBytes(idx));
    }

    private void OnRotateLeft(object sender, RoutedEventArgs e) => Rotate(-90);
    private void OnRotateRight(object sender, RoutedEventArgs e) => Rotate(90);

    private void Rotate(int delta)
    {
        if (!RequireOpen()) return;
        int page = _currentPage;
        _session.Mutate(d => d.RotatePages(new[] { page }, delta));
    }

    private void OnExtractPages(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? spec = InputDialog.Prompt(this, "提取页面",
            $"页码（如 1,3-5；共 {_session.PageCount} 页）：", "1-" + _session.PageCount);
        if (spec == null) return;
        var idx = PageRange.Parse(spec, _session.PageCount);
        if (idx.Length == 0) return;
        var dlg = new Microsoft.Win32.SaveFileDialog { Filter = "PDF (*.pdf)|*.pdf", FileName = "提取.pdf" };
        if (dlg.ShowDialog(this) != true) return;
        try
        {
            _session.Document.ExtractPagesToFile(idx, dlg.FileName);
            MessageBox.Show(this, "已提取到：" + dlg.FileName, "提取");
        }
        catch (Exception ex) { ShowError("提取失败：" + ex.Message); }
    }

    private void OnReorderPages(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? spec = InputDialog.Prompt(this, "重排页面",
            $"按新顺序输入全部页码（如 3,1,2；共 {_session.PageCount} 页）：",
            string.Join(",", Enumerable.Range(1, _session.PageCount)));
        if (spec == null) return;
        var order = PageRange.ParseOrdered(spec, _session.PageCount);
        if (order.Length == 0) return;
        _session.MutateReplace(d => d.ReorderToBytes(order));
    }

    // ------------------------------------------------------------------
    // Menu: document operations
    // ------------------------------------------------------------------
    private void OnMerge(object sender, RoutedEventArgs e)
    {
        var pick = new Microsoft.Win32.OpenFileDialog
        { Filter = "PDF (*.pdf)|*.pdf", Multiselect = true, Title = "选择要合并的 PDF（按顺序）" };
        if (pick.ShowDialog(this) != true || pick.FileNames.Length < 2) return;
        var save = new Microsoft.Win32.SaveFileDialog { Filter = "PDF (*.pdf)|*.pdf", FileName = "合并.pdf" };
        if (save.ShowDialog(this) != true) return;
        try
        {
            var bytes = PdfDocument.MergeFilesToBytes(pick.FileNames);
            File.WriteAllBytes(save.FileName, bytes);
            if (MessageBox.Show(this, "已合并。是否打开结果？", "合并",
                MessageBoxButton.YesNo) == MessageBoxResult.Yes)
                _session.Open(save.FileName);
        }
        catch (Exception ex) { ShowError("合并失败：" + ex.Message); }
    }

    private void OnSplit(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        double? n = InputDialog.PromptNumber(this, "拆分 PDF", "每个文件包含多少页：", 1);
        if (n == null || n < 1) return;
        var folder = new Microsoft.Win32.OpenFolderDialog { Title = "选择输出文件夹" };
        if (folder.ShowDialog(this) != true) return;
        int step = (int)n.Value;
        var ranges = new List<(int, int)>();
        for (int s = 0; s < _session.PageCount; s += step)
            ranges.Add((s, Math.Min(s + step - 1, _session.PageCount - 1)));
        try
        {
            string baseName = _session.Path != null
                ? Path.GetFileNameWithoutExtension(_session.Path) : "doc";
            var written = _session.Document.SplitToFiles(ranges, folder.FolderName, baseName);
            MessageBox.Show(this, $"已拆分为 {written.Count} 个文件。", "拆分");
        }
        catch (Exception ex) { ShowError("拆分失败：" + ex.Message); }
    }

    private void OnWatermark(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? text = InputDialog.Prompt(this, "添加文字水印", "水印文字：", "样本");
        if (string.IsNullOrEmpty(text)) return;
        _session.Mutate(d => d.AddTextWatermark(text));
    }

    private void OnPageNumbers(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? fmt = InputDialog.Prompt(this, "添加页码", "格式（{page} 当前页，{total} 总页）：", "{page} / {total}");
        if (fmt == null) return;
        _session.Mutate(d => d.AddPageNumbers(fmt));
    }

    // ------------------------------------------------------------------
    // Menu: security + metadata (PdfSharp-backed)
    // ------------------------------------------------------------------
    private void OnEncrypt(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? userPw = InputDialog.Prompt(this, "加密", "打开密码（用户密码，可留空）：", "");
        if (userPw == null) return;
        string? ownerPw = InputDialog.Prompt(this, "加密", "权限密码（所有者密码，用于解除限制）：", userPw);
        if (ownerPw == null) return;
        var save = new Microsoft.Win32.SaveFileDialog { Filter = "PDF (*.pdf)|*.pdf", FileName = "加密.pdf" };
        if (save.ShowDialog(this) != true) return;
        try
        {
            PdfSharpOps.EncryptToFile(_session.Document.SaveToBytes(), save.FileName, userPw, ownerPw);
            MessageBox.Show(this, "已加密保存（AES-256）。", "加密");
        }
        catch (Exception ex) { ShowError("加密失败：" + ex.Message); }
    }

    private void OnDecrypt(object sender, RoutedEventArgs e)
    {
        var pick = new OpenFileDialog { Filter = "PDF (*.pdf)|*.pdf", Title = "选择加密的 PDF" };
        if (pick.ShowDialog(this) != true) return;
        string? pw = InputDialog.Prompt(this, "移除密码", "请输入所有者密码：", "");
        if (pw == null) return;
        var save = new Microsoft.Win32.SaveFileDialog { Filter = "PDF (*.pdf)|*.pdf", FileName = "已解密.pdf" };
        if (save.ShowDialog(this) != true) return;
        try
        {
            byte[] clear = PdfSharpOps.DecryptToBytes(File.ReadAllBytes(pick.FileName), pw);
            File.WriteAllBytes(save.FileName, clear);
            MessageBox.Show(this, "已移除密码。", "移除密码");
        }
        catch (Exception ex) { ShowError("移除失败（密码错误或不支持）：" + ex.Message); }
    }

    private void OnMetadata(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        PdfSharpOps.DocInfo info;
        try { info = PdfSharpOps.GetInfo(_session.Document.SaveToBytes()); }
        catch (Exception ex) { ShowError("读取属性失败：" + ex.Message); return; }
        var dlg = new MetadataWindow(info) { Owner = this };
        if (dlg.ShowDialog() != true) return;
        _session.MutateReplace(d => PdfSharpOps.SetInfo(d.SaveToBytes(), dlg.Result));
    }

    // ------------------------------------------------------------------
    // Menu: search + export
    // ------------------------------------------------------------------
    private void OnSearch(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        string? q = InputDialog.Prompt(this, "搜索", "查找内容：", "");
        if (string.IsNullOrEmpty(q)) return;
        var hits = _session.Document.Search(q);
        if (hits.Count == 0) { MessageBox.Show(this, "未找到。", "搜索"); return; }
        var win = new SearchResultsWindow(hits, page => GoToPage(page)) { Owner = this };
        win.Show();
    }

    public void GoToPage(int pageIndex)
    {
        if (pageIndex < 0 || pageIndex >= _hosts.Count) return;
        var h = _hosts[pageIndex];
        var t = h.TransformToAncestor(PagesPanel);
        var pos = t.Transform(new Point(0, 0));
        Scroller.ScrollToVerticalOffset(pos.Y - 20);
    }

    private void OnExportText(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        var dlg = new Microsoft.Win32.SaveFileDialog { Filter = "文本 (*.txt)|*.txt", FileName = "导出.txt" };
        if (dlg.ShowDialog(this) != true) return;
        try
        {
            File.WriteAllText(dlg.FileName, _session.Document.GetAllText());
            MessageBox.Show(this, "已导出文本。", "导出");
        }
        catch (Exception ex) { ShowError("导出失败：" + ex.Message); }
    }

    private void OnExportImages(object sender, RoutedEventArgs e)
    {
        if (!RequireOpen()) return;
        var folder = new Microsoft.Win32.OpenFolderDialog { Title = "选择输出文件夹" };
        if (folder.ShowDialog(this) != true) return;
        try
        {
            for (int i = 0; i < _session.PageCount; i++)
            {
                var rp = _session.Document.RenderPage(i, 2.0);
                var bmp = System.Windows.Media.Imaging.BitmapSource.Create(
                    rp.WidthPx, rp.HeightPx, 96, 96,
                    System.Windows.Media.PixelFormats.Bgra32, null, rp.Pixels, rp.Stride);
                var enc = new System.Windows.Media.Imaging.PngBitmapEncoder();
                enc.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(bmp));
                using var fs = File.Create(Path.Combine(folder.FolderName, $"page_{i + 1:0000}.png"));
                enc.Save(fs);
            }
            MessageBox.Show(this, $"已导出 {_session.PageCount} 张图片。", "导出");
        }
        catch (Exception ex) { ShowError("导出失败：" + ex.Message); }
    }

    private void UpdateCommandStates()
    {
        bool open = _session.IsOpen;
        BtnSave.IsEnabled = open;
        BtnSaveAs.IsEnabled = open;
        BtnEdit.IsEnabled = open;
        BtnUndo.IsEnabled = _session.CanUndo;
        BtnRedo.IsEnabled = _session.CanRedo;
    }

    private void UpdateTitle()
    {
        string name = _session.Path != null ? Path.GetFileName(_session.Path) : "未打开";
        Title = $"Kitty PDF Editor — {name}{(_session.Dirty ? " *" : "")}";
    }

    private void ShowError(string msg) =>
        MessageBox.Show(this, msg, "Kitty PDF", MessageBoxButton.OK, MessageBoxImage.Error);
}
