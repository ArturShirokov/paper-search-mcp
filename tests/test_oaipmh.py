import xml.etree.ElementTree as ET

from paper_search_mcp.academic_platforms.oaipmh import OAIPMHSearcher

RECORD = """
<record xmlns="http://www.openarchives.org/OAI/2.0/">
  <header>
    <identifier>https://example.org/article/1</identifier>
    <datestamp>2026-10-09T04:12:00Z</datestamp>
  </header>
  <metadata>
    <oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"
               xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Leaf title</dc:title>
      <dc:creator>Ada Lovelace</dc:creator>
      <dc:description>Leaf abstract</dc:description>
      <dc:date>2026-10-09</dc:date>
      <dc:publisher>Example Press</dc:publisher>
      <dc:language>ru</dc:language>
    </oai_dc:dc>
  </metadata>
</record>
"""


def test_parse_oai_record_reads_childless_dc_elements():
    # ElementTree elements without children are falsy, so `find(a) or find(b)`
    # used to discard every leaf field.
    paper = OAIPMHSearcher("https://example.org/oai")._parse_oai_record(ET.fromstring(RECORD))

    assert paper.title == "Leaf title"
    assert paper.abstract == "Leaf abstract"
    assert paper.published_date.year == 2026
    assert paper.url == "https://example.org/article/1"
    assert paper.extra["publisher"] == "Example Press"
    assert paper.extra["language"] == "ru"
