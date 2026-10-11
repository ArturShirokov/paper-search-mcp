# Chinese papers: reaching the originals

Fork-only note. Not for upstream pull requests.

Status as of 2026-10-11. Checks were run from a home connection, not the VPS.
R-numbers refer to the research-feed requirements, which live outside this repo.

## What we have now

The `chinarxiv` connector (branch `feat/chinarxiv`) reads ChinaRxiv. ChinaRxiv is a
volunteer project that machine-translates ChinaXiv preprints into English. It gives us:

- English titles, abstracts and full text
- `extra.original_url`, a link to the ChinaXiv abstract page

It does not give us:

- **The Chinese text.** ChinaRxiv only has the translation. A translation can bend a
  claim, and R7 says we must keep every claim and limit as the authors stated them.
- **Fresh papers.** Translations run about 3 weeks behind ChinaXiv. On 2026-10-11
  the newest translated paper was published on 2026-09-21, while ChinaXiv already
  listed October papers.
- **Anything beyond ChinaXiv.** ChinaXiv is one preprint server. Most Chinese
  research appears in Chinese journals, which ChinaRxiv does not cover.

## What we tried, and what happened

| Source | What it is | Result | Notes |
|---|---|---|---|
| ChinaXiv OAI-PMH (`chinaxiv.org/oai/OAIHandler`) | Official harvest feed. Chinese and English metadata | Blocked | Answers "Sorry! You have no right to access this web." on every OAI path. Looks like an IP allowlist |
| ChinaXiv abstract pages (`/abs/<id>`) | Human web pages | Loads (200) | No `citation_*` meta tags found. Would need HTML scraping |
| ChinaXiv search (`/user/search.htm`) | Site search | 403 | |
| ChinaXiv original PDF (`/user/download.htm?uuid=…`) | Original PDF, linked from ChinaRxiv's `pdf_url` | 403 | Same block as the OAI feed |
| SciEngine (`sciengine.com`) | Science China Press journal platform | Home page loads | `/oai` returns an HTML page, not an OAI feed. Not checked further |
| Crossref, Chinese-language query | Already in Layer 1 | Works | "量子计算" since 2026-01-01 gave 17,961 hits. Top hits came from small Singapore-registered Chinese-language publishers, not core Chinese journals |
| OpenAlex `language:zh` | Already in Layer 1 | Works, thin | 39,441 works since 2026-01-01, against 1,272,953 works from Chinese institutions in the same period. Fits the 24% coverage figure in the requirements |
| China DOI (`chinadoi.cn`) | ISTIC, China's own DOI agency | TLS connection failed | Many Chinese journals register DOIs here, not with Crossref. Untested |
| CNKI, Wanfang, CQVIP | The big Chinese journal databases | Home pages load | Paid. Need an institutional login. Out of scope for v1 per the requirements |
| Baidu Scholar (`xueshu.baidu.com`) | Search engine over Chinese papers | Home page loads | Would mean scraping. Fragile, and against their terms |
| NSTL, Sciencepaper Online (`paper.edu.cn`), ScienceDB, CSTR | Government library, preprint site, data and ID registries | Home pages load | Not investigated |

A home page that loads tells us nothing about whether there is an API. Only the rows
marked "Works" or "Blocked" were tested against an API.

## Options, cheapest first

1. **Ask ChinaXiv for OAI access.** The block looks like an allowlist, so the fix may
   just be an email asking for the VPS address to be added. This is the source the
   requirements already name. If it works, the existing `OAIPMHSearcher` base class
   (with the fix on `fix/oaipmh-leaf-elements`) does the harvesting. We still need to
   find the right contact on chinaxiv.org.
2. **Try from another network.** The block may be by region rather than an allowlist.
   Run the same `Identify` request from the Hetzner VPS. If it works there, the feed
   can harvest from the VPS.
   `curl "https://chinaxiv.org/oai/OAIHandler?verb=Identify"`
3. **Ask ChinaRxiv for Chinese metadata.** They already harvest ChinaXiv and hold the
   original PDF links. Their API might be able to return the Chinese title and
   abstract next to the translation. The maintainer is reachable at the contact
   email in their OpenAPI spec.
4. **Use Crossref and OpenAlex in Chinese.** This needs no new code: just search with
   the Chinese terms from R1. Coverage of core journals is weak, so expect noise.
   R6's scoring step would have to filter out low-quality publishers.
5. **Look into Sciencepaper Online, NSTL and China DOI.** Each might have an open
   interface. None was investigated.
6. **Paid access to CNKI or Wanfang.** This is the only route to most Chinese-language
   journals. It needs an institution or a commercial licence. Any future university
   library access is worth checking for a CNKI subscription.

## Questions to settle

- Do the Chinese originals need to be read in full, or would the original title and
  abstract do? An abstract alone would let R7 check the translation's main claims.
- Should Chinese-language items reach Telegram in English with the Chinese title
  kept, like the Russian question in the requirements?
