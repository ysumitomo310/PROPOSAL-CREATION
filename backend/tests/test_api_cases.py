"""案件管理API テスト（TASK-D01）"""

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import openpyxl
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.cases import _resolve_forward_references, router


# ─── Helpers ───


def _create_test_app() -> FastAPI:
    """テスト用 FastAPI アプリ。"""
    app = FastAPI()
    app.include_router(router)
    return app


def _make_excel_bytes(
    headers: list[str],
    rows: list[list],
    sheet_name: str = "Sheet1",
) -> bytes:
    """テスト用 Excel ファイルのバイト列を生成。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _make_column_mapping(
    function_name: str = "機能名",
    **kwargs,
) -> str:
    """テスト用 column_mapping JSON。"""
    mapping = {
        "header_row": kwargs.get("header_row", 1),
        "data_start_row": kwargs.get("data_start_row", 2),
        "columns": {
            "function_name": function_name,
            **{k: v for k, v in kwargs.items() if k not in ("header_row", "data_start_row")},
        },
    }
    return json.dumps(mapping, ensure_ascii=False)


def _mock_session():
    """モック AsyncSession。"""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    return session


# ─── Tests ───


class TestCreateCase:
    @pytest.mark.asyncio
    async def test_create_case_success(self):
        """正常系: Excel アップロード → Case + Requirements 作成。"""
        excel = _make_excel_bytes(
            ["機能名", "要件概要", "重要度"],
            [
                ["受注登録", "受注伝票を作成", "Must"],
                ["出荷処理", "出荷伝票を作成", "Should"],
            ],
        )
        col_mapping = _make_column_mapping(
            function_name="機能名",
            requirement_summary="要件概要",
            importance="重要度",
        )

        session = _mock_session()

        # refresh 時に model_validate 用の属性を設定
        async def _mock_refresh(obj):
            obj.id = "test-case-id"
            obj.name = "テスト案件"
            obj.product = "SAP"
            obj.status = "created"
            obj.total_requirements = 2
            from datetime import datetime
            obj.created_at = datetime.now()

        session.refresh = AsyncMock(side_effect=_mock_refresh)

        app = _create_test_app()

        # session_factory を app.state にセット
        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state = MagicMock()
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/cases",
                files={"file": ("test.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"name": "テスト案件", "product": "SAP", "column_mapping": col_mapping},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "テスト案件"
        assert data["total_requirements"] == 2

    @pytest.mark.asyncio
    async def test_create_case_invalid_column_mapping(self):
        """column_mapping が不正 JSON の場合 422。"""
        excel = _make_excel_bytes(["機能名"], [["テスト"]])

        session = _mock_session()
        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state = MagicMock()
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/cases",
                files={"file": ("test.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"name": "テスト", "column_mapping": "invalid json"},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_case_empty_requirements(self):
        """有効行なし（function_name 空行のみ）→ 422。"""
        excel = _make_excel_bytes(
            ["機能名", "備考"],
            [
                [None, "メモ1"],
                ["", "メモ2"],
            ],
        )
        col_mapping = _make_column_mapping(function_name="機能名")

        session = _mock_session()
        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state = MagicMock()
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/cases",
                files={"file": ("test.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"name": "テスト", "column_mapping": col_mapping},
            )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_case_importance_mapping(self):
        """importance_mapping で値変換が適用される。"""
        excel = _make_excel_bytes(
            ["機能名", "重要度"],
            [["受注登録", "1"], ["出荷処理", "2"]],
        )
        col_mapping = json.dumps({
            "header_row": 1,
            "data_start_row": 2,
            "columns": {
                "function_name": "機能名",
                "importance": "重要度",
                "importance_mapping": {"1": "Must", "2": "Should", "3": "Could"},
            },
        })

        session = _mock_session()
        added_objects = []
        session.add = lambda obj: added_objects.append(obj)

        async def _mock_refresh(obj):
            obj.id = "test-case-id"
            obj.name = "テスト案件"
            obj.product = "SAP"
            obj.status = "created"
            obj.total_requirements = 2
            from datetime import datetime
            obj.created_at = datetime.now()

        session.refresh = AsyncMock(side_effect=_mock_refresh)

        app = _create_test_app()

        class _CM:
            async def __aenter__(self):
                return session
            async def __aexit__(self, *a):
                pass

        factory = MagicMock(return_value=_CM())
        app.state = MagicMock()
        app.state.session_factory = factory

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/cases",
                files={"file": ("test.xlsx", excel, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"name": "テスト", "column_mapping": col_mapping},
            )

        assert resp.status_code == 201
        # FunctionalRequirement の importance が変換されていることを確認
        fr_objects = [o for o in added_objects if hasattr(o, "importance") and hasattr(o, "function_name")]
        assert len(fr_objects) == 2
        assert fr_objects[0].importance == "Must"
        assert fr_objects[1].importance == "Should"


class TestResolveForwardReferences:
    """_resolve_forward_references() 単体テスト。"""

    def _make_rows(self, data: list[dict]) -> list[dict]:
        """テスト用 requirement_rows を生成（sequence_number + original_row_json 付き）。"""
        result = []
        for i, d in enumerate(data, 1):
            row = {
                "sequence_number": i,
                "business_category": d.get("business_category"),
                "business_name": d.get("business_name"),
                "function_name": d.get("function_name", f"機能{i}"),
                "requirement_summary": d.get("requirement_summary"),
                "requirement_detail": d.get("requirement_detail"),
                "importance": d.get("importance"),
                "original_row_json": {},
            }
            result.append(row)
        return result

    def test_dojo_resolved_from_previous_row(self):
        """「同上」が直前行の値に置換される。"""
        rows = self._make_rows([
            {"business_category": "販売管理", "function_name": "受注登録"},
            {"business_category": "同上", "function_name": "出荷処理"},
        ])
        result = _resolve_forward_references(rows)
        assert result[1]["business_category"] == "販売管理"

    def test_ditto_mark_resolved(self):
        """「〃」（ダイトウ記号）が直前行の値に置換される。"""
        rows = self._make_rows([
            {"requirement_summary": "受注伝票を作成する", "function_name": "受注登録"},
            {"requirement_summary": "〃", "function_name": "受注変更"},
        ])
        result = _resolve_forward_references(rows)
        assert result[1]["requirement_summary"] == "受注伝票を作成する"

    def test_douyo_resolved(self):
        """「同様」が直前行の値に置換される。"""
        rows = self._make_rows([
            {"importance": "Must", "function_name": "受注登録"},
            {"importance": "同様", "function_name": "出荷処理"},
        ])
        result = _resolve_forward_references(rows)
        assert result[1]["importance"] == "Must"

    def test_multiple_dojo_in_sequence(self):
        """連続した「同上」が正しく前行値に置換される（連鎖参照）。"""
        rows = self._make_rows([
            {"business_category": "購買管理", "function_name": "発注登録"},
            {"business_category": "同上", "function_name": "発注変更"},
            {"business_category": "同上", "function_name": "発注照会"},
        ])
        result = _resolve_forward_references(rows)
        # 2行目は1行目から解決済み値が入るため、3行目も同じ値になる
        assert result[1]["business_category"] == "購買管理"
        assert result[2]["business_category"] == "購買管理"

    def test_no_dojo_rows_unchanged(self):
        """「同上」がない場合は元の値が保持される。"""
        rows = self._make_rows([
            {"business_category": "販売", "function_name": "受注登録"},
            {"business_category": "購買", "function_name": "発注登録"},
        ])
        result = _resolve_forward_references(rows)
        assert result[0]["business_category"] == "販売"
        assert result[1]["business_category"] == "購買"

    def test_dojo_at_first_row_becomes_none(self):
        """1行目に「同上」がある場合（前行なし）→ None になる。"""
        rows = self._make_rows([
            {"business_category": "同上", "function_name": "受注登録"},
        ])
        result = _resolve_forward_references(rows)
        assert result[0]["business_category"] is None

    def test_multiple_fields_resolved_independently(self):
        """フィールドごとに独立して前行参照が解決される。"""
        rows = self._make_rows([
            {
                "business_category": "販売管理",
                "requirement_summary": "受注処理",
                "function_name": "受注登録",
            },
            {
                "business_category": "同上",
                "requirement_summary": "出荷処理（独自）",
                "function_name": "出荷登録",
            },
        ])
        result = _resolve_forward_references(rows)
        # business_category は同上で解決、requirement_summary は独自値を保持
        assert result[1]["business_category"] == "販売管理"
        assert result[1]["requirement_summary"] == "出荷処理（独自）"

    def test_ueki_to_onaji_resolved(self):
        """「上記と同じ」が直前行の値に置換される。"""
        rows = self._make_rows([
            {"requirement_detail": "詳細テキスト", "function_name": "受注登録"},
            {"requirement_detail": "上記と同じ", "function_name": "受注変更"},
        ])
        result = _resolve_forward_references(rows)
        assert result[1]["requirement_detail"] == "詳細テキスト"

    def test_excel_create_case_with_dojo(self):
        """Excelに「同上」を含む場合、案件作成APIで正しく解決される（統合確認）。"""
        rows = self._make_rows([
            {
                "business_category": "販売",
                "function_name": "受注登録",
                "requirement_summary": "受注伝票を作成",
                "importance": "Must",
            },
            {
                "business_category": "同上",
                "function_name": "出荷処理",
                "requirement_summary": "同上",
                "importance": "同上",
            },
        ])
        result = _resolve_forward_references(rows)
        assert result[1]["business_category"] == "販売"
        assert result[1]["requirement_summary"] == "受注伝票を作成"
        assert result[1]["importance"] == "Must"
