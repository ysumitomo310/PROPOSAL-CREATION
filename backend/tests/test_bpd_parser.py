"""BPDParser テスト（TASK-B02）"""

from pathlib import Path

import pytest

from app.services.knowledge.parser import BPDParser, ScopeItemData

PRODUCT_DOC = Path(__file__).resolve().parent.parent.parent / "product_doc"
SAMPLE_JA = PRODUCT_DOC / "16R_S4CLD2602_BPD_JA_JP.docx"
SAMPLE_EN = PRODUCT_DOC / "16R_S4CLD2602_BPD_EN_JP.docx"
SAMPLE_XLSX = PRODUCT_DOC / "16R_S4CLD2602_BPD_EN_JP.xlsx"


class TestBPDParserExtraction:
    """LLMなしでのパースロジックテスト。"""

    def setup_method(self):
        self.parser = BPDParser(llm_client=None, master_service=None)

    def test_extract_prefix(self):
        assert self.parser._extract_prefix("16R_S4CLD2602_BPD_JA_JP.docx") == "16R"
        assert self.parser._extract_prefix("BD9_S4CLD2602_BPD_JA_JP.docx") == "BD9"
        assert self.parser._extract_prefix("2EL_S4CLD2602_BPD_EN_JP.docx") == "2EL"

    @pytest.mark.skipif(not SAMPLE_JA.exists(), reason="Sample BPD not available")
    def test_extract_function_name(self):
        name = self.parser._extract_function_name(SAMPLE_JA)
        assert name
        assert len(name) > 2
        # タイトルからサフィックスが除去されていること
        assert "_JP)" not in name

    @pytest.mark.skipif(not SAMPLE_JA.exists(), reason="Sample BPD not available")
    def test_parse_ja_docx_sections(self):
        sections = self.parser._parse_ja_docx(SAMPLE_JA)
        # 目的セクションが抽出されること
        assert sections.purpose or sections.procedures
        # テスト手順のプロセス名が抽出されること
        assert len(sections.procedures) >= 1

    @pytest.mark.skipif(not SAMPLE_JA.exists(), reason="Sample BPD not available")
    def test_extract_relations(self):
        sections = self.parser._parse_ja_docx(SAMPLE_JA)
        relations = self.parser._extract_relations(
            sections.business_conditions, sections.procedures
        )
        # リレーションが抽出されるか（あれば related キーがある）
        if relations:
            assert "related" in relations
            for si_id in relations["related"]:
                assert len(si_id) >= 2

    @pytest.mark.skipif(not SAMPLE_EN.exists(), reason="Sample EN BPD not available")
    def test_extract_en_purpose(self):
        en_text = self.parser._extract_en_purpose(SAMPLE_EN)
        assert isinstance(en_text, str)

    @pytest.mark.skipif(not SAMPLE_JA.exists(), reason="Sample BPD not available")
    def test_extract_keywords(self):
        sections = self.parser._parse_ja_docx(SAMPLE_JA)
        name = self.parser._extract_function_name(SAMPLE_JA)
        keywords = self.parser._extract_keywords(name, sections)
        assert isinstance(keywords, list)
        assert len(keywords) <= 10

    @pytest.mark.skipif(not SAMPLE_JA.exists(), reason="Sample BPD not available")
    @pytest.mark.asyncio
    async def test_parse_scope_item_no_llm(self):
        """LLMなしでのフルパース（description=purposeテキスト）。"""
        result = await self.parser.parse_scope_item(
            SAMPLE_JA, SAMPLE_EN, SAMPLE_XLSX
        )
        assert isinstance(result, ScopeItemData)
        assert result.id == "SAP-16R"
        assert result.scope_item_id == "16R"
        assert result.product_namespace == "SAP"
        assert result.function_name
        assert len(result.function_name) > 2
