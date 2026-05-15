"""Side panels: thumbnails, outline (bookmarks), search results."""

from __future__ import annotations

from typing import Optional

import fitz
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .document import PdfDocument


THUMB_WIDTH = 140


def render_thumb(page: fitz.Page, width: int = THUMB_WIDTH) -> QPixmap:
    rect = page.rect
    scale = width / max(rect.width, 1.0)
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False, annots=True)
    fmt = QImage.Format.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    return QPixmap.fromImage(img)


class ThumbnailPanel(QWidget):
    pageSelected = pyqtSignal(int)
    pagesReordered = pyqtSignal(list)  # new order list of original indices
    pageDeleteRequested = pyqtSignal(list)
    pageRotateRequested = pyqtSignal(list, int)  # indices, angle
    pageDuplicateRequested = pyqtSignal(list)
    pageInsertBlankRequested = pyqtSignal(int)
    pageExtractRequested = pyqtSignal(list)

    def __init__(self, document: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = document
        self.list = QListWidget(self)
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.4)))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Snap)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(6)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_menu)
        self.list.itemSelectionChanged.connect(self._on_selection)
        self.list.model().rowsMoved.connect(self._on_rows_moved)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.list)

        self.doc.documentReplaced.connect(self.rebuild)
        self.doc.pagesChanged.connect(self.rebuild)
        self.doc.pageContentChanged.connect(self.refresh_one)

    def rebuild(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        if self.doc.is_open():
            for i in range(self.doc.page_count):
                pix = render_thumb(self.doc.page(i))
                item = QListWidgetItem()
                item.setIcon(QIcon(pix))
                item.setText(f"{i + 1}")
                item.setData(Qt.ItemDataRole.UserRole, i)  # original index
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setSizeHint(QSize(THUMB_WIDTH + 12, int(THUMB_WIDTH * 1.4) + 24))
                self.list.addItem(item)
        self.list.blockSignals(False)

    def refresh_one(self, index: int) -> None:
        if 0 <= index < self.list.count() and self.doc.is_open():
            try:
                pix = render_thumb(self.doc.page(index))
                self.list.item(index).setIcon(QPixmap(pix))
            except Exception:
                pass

    def select_page(self, index: int) -> None:
        if 0 <= index < self.list.count():
            self.list.blockSignals(True)
            self.list.setCurrentRow(index)
            self.list.blockSignals(False)

    def _on_selection(self) -> None:
        if self.list.currentItem() is not None:
            self.pageSelected.emit(self.list.currentRow())

    def _on_rows_moved(self, *args) -> None:
        # When an internal move happens, the UserRole values keep the
        # ORIGINAL index; collect current order and emit.
        new_order = []
        for i in range(self.list.count()):
            new_order.append(self.list.item(i).data(Qt.ItemDataRole.UserRole))
        # Only emit if order actually changed
        if new_order != list(range(self.list.count())):
            self.pagesReordered.emit(new_order)

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("在末尾插入空白页", lambda: self.pageInsertBlankRequested.emit(self.list.count()))
            menu.exec(self.list.mapToGlobal(pos))
            return
        selected = [self.list.row(i) for i in self.list.selectedItems()]
        if self.list.row(item) not in selected:
            selected = [self.list.row(item)]
        menu = QMenu(self)
        menu.addAction("顺时针旋转", lambda: self.pageRotateRequested.emit(selected, 90))
        menu.addAction("旋转 180°", lambda: self.pageRotateRequested.emit(selected, 180))
        menu.addAction("逆时针旋转", lambda: self.pageRotateRequested.emit(selected, -90))
        menu.addSeparator()
        menu.addAction("复制此页", lambda: self.pageDuplicateRequested.emit(selected))
        menu.addAction("在此页后插入空白页", lambda: self.pageInsertBlankRequested.emit(max(selected) + 1))
        menu.addAction("提取为新 PDF…", lambda: self.pageExtractRequested.emit(selected))
        menu.addSeparator()
        menu.addAction("删除页面", lambda: self.pageDeleteRequested.emit(selected))
        menu.exec(self.list.mapToGlobal(pos))


class OutlinePanel(QWidget):
    locationSelected = pyqtSignal(int)  # page index to jump to

    def __init__(self, document: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = document
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["书签", "页码"])
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self.tree)

        btn_row = QHBoxLayout()
        b1 = QPushButton("添加")
        b1.clicked.connect(self._add_bookmark)
        b2 = QPushButton("删除")
        b2.clicked.connect(self._remove_bookmark)
        b3 = QPushButton("重命名")
        b3.clicked.connect(self._rename_bookmark)
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
        btn_row.addWidget(b3)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.doc.documentReplaced.connect(self.rebuild)
        self.doc.pagesChanged.connect(self.rebuild)

    def rebuild(self) -> None:
        self.tree.clear()
        if not self.doc.is_open():
            return
        toc = self.doc.toc()
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in toc:
            if len(entry) < 3:
                continue
            level, title, page = entry[0], entry[1], entry[2]
            node = QTreeWidgetItem([title, str(page)])
            node.setData(0, Qt.ItemDataRole.UserRole, page - 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else None
            if parent:
                parent.addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((level, node))
        self.tree.expandAll()

    def _on_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page = item.data(0, Qt.ItemDataRole.UserRole)
        if page is not None:
            self.locationSelected.emit(int(page))

    def _on_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item:
            menu.addAction("重命名", self._rename_bookmark)
            menu.addAction("删除", self._remove_bookmark)
            menu.addSeparator()
        menu.addAction("为当前页添加书签", self._add_bookmark)
        menu.exec(self.tree.mapToGlobal(pos))

    def _flatten(self) -> list[list]:
        """Walk the tree and produce a fresh TOC list."""
        toc: list[list] = []

        def walk(item: QTreeWidgetItem, level: int) -> None:
            page = item.data(0, Qt.ItemDataRole.UserRole)
            try:
                page = int(page) + 1
            except Exception:
                page = 1
            toc.append([level, item.text(0), page])
            for i in range(item.childCount()):
                walk(item.child(i), level + 1)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 1)
        return toc

    def _add_bookmark(self) -> None:
        if not self.doc.is_open():
            return
        title, ok = QInputDialog.getText(self, "添加书签", "标题：")
        if not ok or not title:
            return
        page, ok = QInputDialog.getInt(self, "添加书签", "页码（从 1 开始）：", 1, 1, self.doc.page_count)
        if not ok:
            return
        toc = self.doc.toc()
        toc.append([1, title, page])
        self.doc.set_toc(toc)

    def _remove_bookmark(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        else:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self.doc.set_toc(self._flatten())

    def _rename_bookmark(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        title, ok = QInputDialog.getText(self, "重命名书签", "标题：", text=item.text(0))
        if not ok or not title:
            return
        item.setText(0, title)
        self.doc.set_toc(self._flatten())


class SearchPanel(QWidget):
    searchRequested = pyqtSignal(str)
    clearRequested = pyqtSignal()
    resultActivated = pyqtSignal(int, object)  # page index, rect

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        row = QHBoxLayout()
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("在文档中搜索…")
        self.edit.returnPressed.connect(self._emit_search)
        btn = QPushButton("查找")
        btn.clicked.connect(self._emit_search)
        clr = QPushButton("清除")
        clr.clicked.connect(self.clearRequested)
        row.addWidget(self.edit)
        row.addWidget(btn)
        row.addWidget(clr)
        layout.addLayout(row)
        self.results = QListWidget(self)
        self.results.itemActivated.connect(self._on_activated)
        self.results.itemClicked.connect(self._on_activated)
        layout.addWidget(self.results)
        self.status = QLabel("")
        layout.addWidget(self.status)

    def _emit_search(self) -> None:
        text = self.edit.text().strip()
        if text:
            self.searchRequested.emit(text)

    def set_results(self, hits: list[tuple[int, fitz.Rect, str]]) -> None:
        self.results.clear()
        for page_index, rect, snippet in hits:
            it = QListWidgetItem(f"第 {page_index + 1} 页  {snippet}")
            it.setData(Qt.ItemDataRole.UserRole, (page_index, rect))
            self.results.addItem(it)
        self.status.setText(f"共 {len(hits)} 处匹配")

    def _on_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            page_index, rect = data
            self.resultActivated.emit(page_index, rect)
