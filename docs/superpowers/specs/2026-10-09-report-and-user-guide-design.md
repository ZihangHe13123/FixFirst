# B11 report and B14 user guide

## Approval and scope

The user approved B11 and B14 on 9 October 2026: “可以开始做b11和b14”. The preceding proposal specified a report using A2, B3 and completed local B7 evidence, and a guide covering the human interface and MCP. This document records that approved scope.

## Deliverables

- A new English report version, based on the retained v0.1 Word skeleton, with a readable PDF and a source register. Preserve the six course sections and appendices. Populate completed experiments; disclose development data, uncertain diagnoses, missing responses, scoring sensitivity and version differences.
- `docs/USER_GUIDE.md`, with an English Word/PDF companion for the installation appendix. Cover setup, the supplied sample, own projects with and without tests, interpretation, CLI, MCP, troubleshooting and uninstall.
- Actual screenshots of the frozen product and a recorded sample repair. Verify CLI syntax and MCP examples without a language model. Leave Windows real-device acceptance to the teammate.
- A short checklist identifying remaining external results and human contributions.

## Evidence and boundaries

The product and runner remain at `b7-freeze-20261007`, commit `5c224cf`. This branch contains documentation only. It does not alter the scheduled DeepSeek registration, task pack, environment, model or original scores.

A2 and B3 use their recorded versions, not the current model. B7 uses 22 constructed tasks, with 18 in-scope tasks in the main analysis. The report distinguishes root-cause accuracy, human-rated advice and executed repair success. It reports the strict H5 result together with the registered sensitivity result.

DeepSeek, real participant data, final Windows acceptance, B12 phase two and B17 results are not invented. Their status is stated explicitly, with a separate completion checklist. Individual reflections and narration are written or recorded by the people concerned.

## Document design and validation

Use the existing report's section order and Word styles, with black headings, readable tables and captions. Retain the original Word file. Render new Word outputs with the bundled LibreOffice and inspect every page. Verify numbers against the original artifacts and save their hashes. Test the guide's sample and MCP flow on macOS, record exact outcomes and keep test files unchanged.

## Work checklist

- [x] Review the course requirements and retained report.
- [x] Confirm the approved scope and isolate a documentation branch.
- [ ] Extract and bind the completed experiment results.
- [ ] Write the report and usage guide.
- [ ] Verify the sample, CLI and MCP commands.
- [ ] Render and inspect all document pages.
- [ ] Commit the documentation and provide a concise review handoff.
