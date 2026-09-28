"""Qt list model mirroring DownloadManager.jobs, plus a status filter."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt

from ..engine import ACTIVE, DownloadManager, Status

JobRole = Qt.UserRole + 1

FILTERS = {
    "all": None,
    "active": ACTIVE | {Status.QUEUED},
    "done": {Status.DONE, Status.SKIPPED},
    "failed": {Status.FAILED, Status.CANCELLED},
}


class JobModel(QAbstractListModel):
    def __init__(self, manager: DownloadManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._ids: list[int] = []
        self._jobs: dict = {}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._ids):
            return None
        job = self._jobs[self._ids[index.row()]]
        if role == JobRole:
            return job
        if role == Qt.DisplayRole:
            return job.display_title
        if role == Qt.ToolTipRole:
            return None  # handled by the delegate
        return None

    def sync(self):
        """Bring rows in line with the manager's job list with minimal model signals."""
        jobs = list(self.manager.jobs)
        new_ids = [j.id for j in jobs]
        if new_ids == self._ids:
            return
        new_set = set(new_ids)
        for row in range(len(self._ids) - 1, -1, -1):  # removals, bottom-up
            if self._ids[row] not in new_set:
                self.beginRemoveRows(QModelIndex(), row, row)
                self._jobs.pop(self._ids.pop(row), None)
                self.endRemoveRows()
        old_set = set(self._ids)
        if [i for i in new_ids if i in old_set] != self._ids:  # reordered: rare, just reset
            self.beginResetModel()
            self._ids = new_ids
            self._jobs = {j.id: j for j in jobs}
            self.endResetModel()
            return
        for row, job in enumerate(jobs):  # insertions in order
            if row >= len(self._ids) or self._ids[row] != job.id:
                self.beginInsertRows(QModelIndex(), row, row)
                self._ids.insert(row, job.id)
                self._jobs[job.id] = job
                self.endInsertRows()

    def refresh(self, ids):
        for jid in ids:
            try:
                row = self._ids.index(jid)
            except ValueError:
                continue
            idx = self.index(row)
            self.dataChanged.emit(idx, idx)

    def refresh_all(self):
        if self._ids:
            self.dataChanged.emit(self.index(0), self.index(len(self._ids) - 1))

    def rows_with_thumbnail(self, url: str):
        return [r for r, jid in enumerate(self._ids) if self._jobs[jid].thumbnail == url]


class FilterModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "all"

    def set_mode(self, mode: str):
        if hasattr(self, "endFilterChange"):  # Qt >= 6.10
            self.beginFilterChange()
            self.mode = mode
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.mode = mode
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, row, parent):
        statuses = FILTERS.get(self.mode)
        if statuses is None:
            return True
        job = self.sourceModel().index(row, 0, parent).data(JobRole)
        return job is not None and job.status in statuses
