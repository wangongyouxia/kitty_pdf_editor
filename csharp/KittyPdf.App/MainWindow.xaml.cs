using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using Microsoft.Win32;

namespace KittyPdf.App;

public partial class MainWindow : Window
{
    private readonly PdfSession _session = new();
    private readonly List<PageHost> _hosts = new();
    private double _zoom = 1.0;
    private EditController? _edit;

    public MainWindow()
    {
        InitializeComponent();
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
        catch (Exception ex) { ShowError("打开失败：" + ex.Message); }
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
        }
    }

    // ------------------------------------------------------------------
    // Edit mode toggle
    // ------------------------------------------------------------------
    private void OnToggleEdit(object sender, RoutedEventArgs e)
    {
        if (!_session.IsOpen) { BtnEdit.IsChecked = false; return; }
        _edit ??= new EditController(this, _session);
        _edit.Rebuild(_hosts);
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
