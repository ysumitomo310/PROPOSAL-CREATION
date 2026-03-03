"""ModuleOverviewParser テスト（TASK-B03）"""

from pathlib import Path

import pytest

from app.services.knowledge.parser import ModuleOverviewData, ModuleOverviewParser

PRODUCT_DOC = Path(__file__).resolve().parent.parent.parent / "product_doc"
SAMPLE_PDF = PRODUCT_DOC / "20240527_01_Discovery WS用_SAP S4HANA Cloud Public Edition_SDソリューション(在庫販売).pdf"


class TestModuleOverviewParser:
    """LLMなしでのPDFパースロジックテスト。"""

    def setup_method(self):
        self.parser = ModuleOverviewParser(llm_client=None)

    def test_detect_module_sd(self):
        module, name = self.parser._detect_module(
            "20240527_01_Discovery WS用_SAP S4HANA Cloud Public Edition_SDソリューション(在庫販売).pdf"
        )
        assert module == "SD"

    def test_detect_module_mm(self):
        module, name = self.parser._detect_module(
            "20240604__Discovery WS用_SAP S4HANA Cloud Public Edition_購買ソリューション.pdf"
        )
        assert module == "MM"

    def test_detect_module_ps(self):
        module, name = self.parser._detect_module(
            "20240527_Discovery WS用_SAP S4HANA Cloud Public Edition_プロフェッショナルサービス.pdf"
        )
        assert module == "PS"

    @pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="Sample PDF not available")
    def test_extract_text(self):
        text, page_count = self.parser._extract_text(SAMPLE_PDF)
        assert page_count > 0
        assert len(text) > 100

    @pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="Sample PDF not available")
    def test_detect_scope_item_references(self):
        text, _ = self.parser._extract_text(SAMPLE_PDF)
        refs = self.parser._detect_scope_item_references(text)
        assert isinstance(refs, list)
        # SDソリューション(在庫販売)なのでBD9等が含まれる可能性が高い
        if refs:
            for ref in refs:
                assert len(ref) >= 2
                assert ref == ref.upper() or any(c.isdigit() for c in ref)

    @pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="Sample PDF not available")
    @pytest.mark.asyncio
    async def test_parse_module_overview_no_llm(self):
        """LLMなしでのフルパース（summary=先頭テキスト）。"""
        result = await self.parser.parse_module_overview(SAMPLE_PDF)
        assert isinstance(result, ModuleOverviewData)
        assert result.module == "SD"
        assert result.product_namespace == "SAP"
        assert result.page_count > 0
        assert result.source_doc
        assert result.summary
