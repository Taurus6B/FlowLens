"""统计与报表模块 —— 导出通用报表（CSV / XLSX / HTML）。

三种格式共用同一份数据快照，字段与口径完全一致：
  * CSV   —— 带 BOM 的 UTF-8，Excel / WPS / Numbers 直接双击打开不乱码
  * XLSX  —— 多工作表（总览 / 应用排行 / 每日趋势 / 应用详情），带表头样式
  * HTML  —— 单文件网页报表，可直接打印成 PDF
"""
from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from ..core.daterange import DateRange, day_str
from ..core.units import format_bytes, format_percent
from ..core.models import AppAggregate, AppDetail, Overview
from .aggregator import StatsService

CALIBER_NOTE = "统计口径：总流量 = 上传流量 + 下载流量；单位自动换算（1 KB = 1024 B）。"


@dataclass
class ReportBundle:
    overview: Overview
    ranking: list[AppAggregate]
    detail: AppDetail | None = None

    @property
    def range(self) -> DateRange:
        return DateRange(self.overview.start, self.overview.end)

    @property
    def total(self) -> int:
        return self.overview.total


class ReportExporter:
    def __init__(self, stats: StatsService):
        self.stats = stats

    # ------------------------------------------------------------------ 快照
    def build(self, rng: DateRange, app_id: int | None = None) -> ReportBundle:
        return ReportBundle(
            overview=self.stats.overview(rng),
            ranking=self.stats.ranking(rng, sort_by="total", descending=True),
            detail=self.stats.app_detail(app_id, rng) if app_id else None,
        )

    # ------------------------------------------------------------------ 入口
    def export(self, path: str | Path, rng: DateRange, *, fmt: str | None = None,
               app_id: int | None = None, source_label: str = "") -> Path:
        path = Path(path)
        fmt = (fmt or path.suffix.lstrip(".")).lower()
        bundle = self.build(rng, app_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "csv":
            self._write_csv(path, bundle, source_label)
        elif fmt in ("xlsx", "xls"):
            self._write_xlsx(path, bundle, source_label)
        elif fmt in ("html", "htm"):
            self._write_html(path, bundle, source_label)
        else:
            raise ValueError(f"不支持的导出格式：{fmt}")
        return path

    # ------------------------------------------------------------------ CSV
    def _write_csv(self, path: Path, b: ReportBundle, source_label: str) -> None:
        ov = b.overview
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["网络流量统计报表"])
            w.writerow(["统计周期", f"{day_str(ov.start)} 至 {day_str(ov.end)}",
                        "天数", DateRange(ov.start, ov.end).length])
            w.writerow(["生成时间", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "数据来源", source_label or "本机采集"])
            w.writerow(["口径说明", CALIBER_NOTE])
            w.writerow([])

            w.writerow(["汇总"])
            w.writerow(["上传流量(字节)", "下载流量(字节)", "总流量(字节)",
                        "上传(可读)", "下载(可读)", "总流量(可读)", "活跃应用数", "有数据天数"])
            w.writerow([ov.upload, ov.download, ov.total, format_bytes(ov.upload),
                        format_bytes(ov.download), format_bytes(ov.total),
                        ov.active_apps, ov.days_with_data])
            w.writerow([])

            w.writerow(["应用排行"])
            w.writerow(["名次", "应用", "类型", "上传(字节)", "下载(字节)", "总流量(字节)",
                        "上传(可读)", "下载(可读)", "总流量(可读)", "占总流量比例", "活跃天数"])
            for app in b.ranking:
                w.writerow([app.rank, app.name, _kind_name(app.kind), app.upload,
                            app.download, app.total, format_bytes(app.upload),
                            format_bytes(app.download), format_bytes(app.total),
                            format_percent(app.share), app.days_active])
            w.writerow([])

            w.writerow(["每日趋势"])
            w.writerow(["日期", "上传(字节)", "下载(字节)", "总流量(字节)",
                        "上传(可读)", "下载(可读)", "总流量(可读)"])
            for p in ov.series:
                w.writerow([day_str(p.day), p.upload, p.download, p.total,
                            format_bytes(p.upload), format_bytes(p.download),
                            format_bytes(p.total)])

            if b.detail:
                d = b.detail
                w.writerow([])
                w.writerow([f"应用详情：{d.app.name}"])
                w.writerow(["日期", "上传(字节)", "下载(字节)", "总流量(字节)",
                            "占当日总流量", "占该应用总流量"])
                for r in d.rows:
                    w.writerow([day_str(r.day), r.upload, r.download, r.total,
                                format_percent(r.app_share_of_day), format_percent(r.app_share)])

    # ------------------------------------------------------------------ XLSX
    def _write_xlsx(self, path: Path, b: ReportBundle, source_label: str) -> None:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError as exc:      # pragma: no cover
            raise RuntimeError("导出 XLSX 需要 openpyxl，请执行：pip install openpyxl") from exc

        ov = b.overview
        wb = Workbook()
        head_font = Font(bold=True, color="FFFFFF")
        head_fill = PatternFill("solid", fgColor="3B6BF5")
        sub_fill = PatternFill("solid", fgColor="EEF2FF")

        def style_header(ws, row_idx: int, cols: int):
            for c in range(1, cols + 1):
                cell = ws.cell(row=row_idx, column=c)
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = Alignment(horizontal="center", vertical="center")

        # —— 总览
        ws = wb.active
        ws.title = "总览"
        rows = [
            ("网络流量统计报表", ""),
            ("统计周期", f"{day_str(ov.start)} 至 {day_str(ov.end)}（{DateRange(ov.start, ov.end).length} 天）"),
            ("生成时间", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("数据来源", source_label or "本机采集"),
            ("口径说明", CALIBER_NOTE),
            ("", ""),
            ("上传流量", format_bytes(ov.upload)),
            ("下载流量", format_bytes(ov.download)),
            ("总流量", format_bytes(ov.total)),
            ("活跃应用数", ov.active_apps),
            ("有数据天数", ov.days_with_data),
            ("未分类流量", format_bytes(ov.unclassified)),
        ]
        for r in rows:
            ws.append(list(r))
        ws["A1"].font = Font(bold=True, size=14)
        for r in range(2, 7):
            ws.cell(row=r, column=1).font = Font(bold=True)
            ws.cell(row=r, column=1).fill = sub_fill
        ws.column_dimensions["A"].width = 16
        ws.column_dimensions["B"].width = 52

        # —— 应用排行
        ws2 = wb.create_sheet("应用排行")
        headers = ["名次", "应用", "类型", "上传(字节)", "下载(字节)", "总流量(字节)",
                   "上传", "下载", "总流量", "占总流量比例", "活跃天数"]
        ws2.append(headers)
        style_header(ws2, 1, len(headers))
        for app in b.ranking:
            ws2.append([app.rank, app.name, _kind_name(app.kind), app.upload,
                        app.download, app.total, format_bytes(app.upload),
                        format_bytes(app.download), format_bytes(app.total),
                        app.share, app.days_active])
        for row in ws2.iter_rows(min_row=2, min_col=10, max_col=10):
            for cell in row:
                cell.number_format = "0.0%"
        widths2 = [6, 26, 10, 14, 14, 14, 12, 12, 12, 14, 10]
        for i, wdt in enumerate(widths2, start=1):
            ws2.column_dimensions[get_column_letter(i)].width = wdt
        ws2.freeze_panes = "A2"

        # —— 每日趋势
        ws3 = wb.create_sheet("每日趋势")
        headers3 = ["日期", "上传(字节)", "下载(字节)", "总流量(字节)", "上传", "下载", "总流量"]
        ws3.append(headers3)
        style_header(ws3, 1, len(headers3))
        for p in ov.series:
            ws3.append([day_str(p.day), p.upload, p.download, p.total,
                        format_bytes(p.upload), format_bytes(p.download), format_bytes(p.total)])
        for i, wdt in enumerate([14, 14, 14, 14, 12, 12, 12], start=1):
            ws3.column_dimensions[get_column_letter(i)].width = wdt
        ws3.freeze_panes = "A2"

        # —— 应用详情
        if b.detail:
            d = b.detail
            ws4 = wb.create_sheet("应用详情")
            ws4.append([f"应用详情：{d.app.name}"])
            ws4["A1"].font = Font(bold=True, size=13)
            ws4.append([f"统计周期：{day_str(d.start)} 至 {day_str(d.end)}　"
                        f"总流量：{format_bytes(d.app.total)}　"
                        f"占比：{format_percent(d.app.share)}"])
            ws4.append([])
            headers4 = ["日期", "上传(字节)", "下载(字节)", "总流量(字节)",
                        "占当日总流量", "占该应用总流量"]
            ws4.append(headers4)
            style_header(ws4, 4, len(headers4))
            for r in d.rows:
                ws4.append([day_str(r.day), r.upload, r.download, r.total,
                            r.app_share_of_day, r.app_share])
            for row in ws4.iter_rows(min_row=5, min_col=5, max_col=6):
                for cell in row:
                    cell.number_format = "0.0%"
            for i, wdt in enumerate([14, 14, 14, 14, 16, 18], start=1):
                ws4.column_dimensions[get_column_letter(i)].width = wdt

        wb.save(str(path))

    # ------------------------------------------------------------------ HTML
    def _write_html(self, path: Path, b: ReportBundle, source_label: str) -> None:
        ov = b.overview
        mx = max((p.total for p in ov.series), default=0) or 1
        bars = []
        for p in ov.series:
            h = max(2, int(p.total / mx * 120))
            hu = int(h * (p.upload / p.total)) if p.total else 0
            bars.append(
                f'<div class="bar" title="{day_str(p.day)} 总 {format_bytes(p.total)}">'
                f'<div class="fill" style="height:{h}px">'
                f'<i style="height:{hu}px"></i></div>'
                f'<span>{p.day.month:02d}-{p.day.day:02d}</span></div>'
            )
        rank_rows = "\n".join(
            f"<tr><td class='c'>{a.rank}</td><td>{_esc(a.name)}"
            f"{('<em>' + _kind_label(a.kind) + '</em>') if _kind_label(a.kind) else ''}</td>"
            f"<td class='n'>{format_bytes(a.upload)}</td>"
            f"<td class='n'>{format_bytes(a.download)}</td>"
            f"<td class='n b'>{format_bytes(a.total)}</td>"
            f"<td class='n'>{format_percent(a.share)}</td>"
            f"<td class='c'>{a.days_active}</td></tr>"
            for a in b.ranking
        )
        detail_block = ""
        if b.detail:
            d = b.detail
            drows = "\n".join(
                f"<tr><td class='c'>{day_str(r.day)}</td>"
                f"<td class='n'>{format_bytes(r.upload)}</td>"
                f"<td class='n'>{format_bytes(r.download)}</td>"
                f"<td class='n b'>{format_bytes(r.total)}</td>"
                f"<td class='n'>{format_percent(r.app_share_of_day)}</td>"
                f"<td class='n'>{format_percent(r.app_share)}</td></tr>"
                for r in d.rows
            )
            detail_block = f"""
  <h2>应用详情 · {_esc(d.app.name)}</h2>
  <p class="muted">周期内总流量 {format_bytes(d.app.total)}，
     占全网 {format_percent(d.app.share)}，活跃 {d.app.days_active} 天</p>
  <table><thead><tr><th>日期</th><th>上传</th><th>下载</th><th>总流量</th>
  <th>占当日总流量</th><th>占该应用总流量</th></tr></thead><tbody>{drows}</tbody></table>"""

        html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>网络流量统计报表 {day_str(ov.start)} ~ {day_str(ov.end)}</title>
<style>
  :root{{--fg:#1b2130;--muted:#6b7280;--line:#e8eaf0;--primary:#3b6bf5;--bg:#f5f6fa;}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:32px;background:var(--bg);color:var(--fg);
       font:14px/1.6 "Microsoft YaHei UI","Segoe UI",system-ui,sans-serif}}
  .wrap{{max-width:1040px;margin:0 auto}}
  h1{{font-size:22px;margin:0 0 6px}}
  h2{{font-size:16px;margin:28px 0 10px}}
  .muted{{color:var(--muted);font-size:13px;margin:0 0 6px}}
  .card{{background:#fff;border:1px solid var(--line);border-radius:12px;
         padding:20px 22px;margin-bottom:18px}}
  .kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:14px}}
  .kpi{{background:var(--bg);border-radius:10px;padding:12px 14px}}
  .kpi span{{display:block;color:var(--muted);font-size:12px}}
  .kpi b{{font-size:18px;font-weight:600}}
  .chart{{display:flex;align-items:flex-end;gap:4px;height:150px;
          padding-top:20px;overflow-x:auto}}
  .bar{{flex:1 0 12px;display:flex;flex-direction:column;justify-content:flex-end;
        align-items:center;height:140px}}
  .fill{{width:100%;background:var(--primary);border-radius:4px 4px 0 0;
         display:flex;flex-direction:column;justify-content:flex-start;overflow:hidden}}
  .fill i{{display:block;width:100%;background:#ffab48;flex:0 0 auto}}
  .bar span{{font-size:10px;color:var(--muted);margin-top:4px}}
  table{{width:100%;border-collapse:collapse;font-size:13px;background:#fff}}
  th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}}
  th{{background:#f0f3ff;color:#31406b;font-weight:600;font-size:12px}}
  td.n{{text-align:right;font-variant-numeric:tabular-nums}}
  td.c{{text-align:center;color:var(--muted)}}
  td.b{{font-weight:600}}
  td em{{font-style:normal;font-size:11px;color:var(--muted);margin-left:6px;
         background:var(--bg);padding:1px 5px;border-radius:4px}}
  footer{{color:var(--muted);font-size:12px;margin-top:22px;text-align:center}}
</style></head><body><div class="wrap">
  <div class="card">
    <h1>网络流量统计报表</h1>
    <p class="muted">统计周期 {day_str(ov.start)} 至 {day_str(ov.end)}
       （{DateRange(ov.start, ov.end).length} 天）　数据来源：{_esc(source_label or '本机采集')}
       　生成时间：{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <div class="kpis">
      <div class="kpi"><span>总流量</span><b>{format_bytes(ov.total)}</b></div>
      <div class="kpi"><span>下载流量</span><b>{format_bytes(ov.download)}</b></div>
      <div class="kpi"><span>上传流量</span><b>{format_bytes(ov.upload)}</b></div>
      <div class="kpi"><span>活跃应用</span><b>{ov.active_apps}</b></div>
    </div>
  </div>

  <div class="card">
    <h2 style="margin-top:0">每日流量趋势</h2>
    <p class="muted">蓝色为下载，橙色为上传；柱高表示当日总流量</p>
    <div class="chart">{''.join(bars)}</div>
  </div>

  <div class="card">
    <h2 style="margin-top:0">应用流量排行</h2>
    <table><thead><tr><th>#</th><th>应用</th><th>上传</th><th>下载</th>
    <th>总流量</th><th>占比</th><th>活跃天数</th></tr></thead>
    <tbody>{rank_rows}</tbody></table>
  </div>
  {detail_block}
  <footer>{CALIBER_NOTE}<br>由 FlowLens（流量镜）生成</footer>
</div></body></html>"""
        path.write_text(html, encoding="utf-8")


def _kind_name(kind: str) -> str:
    """表格中的类型列取值。"""
    return {"system": "系统", "unclassified": "未分类"}.get(kind, "应用")


def _kind_label(kind: str) -> str:
    """HTML 报表中的标签：仅系统/未分类显示，普通应用不加噪声。"""
    return {"system": "系统", "unclassified": "未分类"}.get(kind, "")


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
