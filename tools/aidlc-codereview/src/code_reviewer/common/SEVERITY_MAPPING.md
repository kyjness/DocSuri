# Severity Classification Policy

This document defines the severity classification standard for the AIDLC Code Reviewer. All tool wrappers (Java and Python) must follow this policy.

---

## Core Rule

**HIGH and CRITICAL are reserved exclusively for security-category findings.** Non-security categories (linting, type safety, complexity, duplication, dead code) must cap at MEDIUM.

---

## 1. Severity Levels

| Level        | When to Use                                                            | Examples                                                                                    |
| ------------ | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **CRITICAL** | Exploitable security vulnerabilities with direct impact                | RCE, SQL injection (high confidence), command injection                                     |
| **HIGH**     | Security issues requiring immediate attention                          | Hardcoded secrets, insecure crypto, SSRF, XSS, deserialization flaws                        |
| **MEDIUM**   | Significant non-security issues, or lower-confidence security findings | Type errors, high complexity (D-F rank), style errors, large duplication, security warnings |
| **LOW**      | Minor issues that should be addressed but aren't urgent                | Style warnings, small duplication, low-confidence dead code, minor linting                  |
| **INFO**     | Informational, no action required                                      | Low complexity grades (A), notes, ignored findings                                          |

---

## 2. Tool Mappings

### 2.1 Security Tools (HIGH/CRITICAL allowed)

#### Semgrep (Java + Python)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| `ERROR`              | HIGH            |
| `WARNING`            | MEDIUM          |
| `INFO`               | LOW             |
| Unknown / default    | LOW             |

Consistent across both languages.

#### Gitleaks (Java + Python)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| All detected secrets | HIGH            |

Consistent across both languages.

#### Bandit (Python only)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| `HIGH`               | HIGH            |
| `MEDIUM`             | MEDIUM          |
| `LOW`                | LOW             |
| Unknown / default    | INFO            |

### 2.2 Linting / Style Tools (capped at MEDIUM)

#### Checkstyle (Java)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| `error`              | MEDIUM          |
| `warning`            | LOW             |
| `info`               | INFO            |
| `ignore`             | INFO            |

#### Ruff (Python)

| Rule Code Prefix          | Mapped Severity |
| ------------------------- | --------------- |
| `E` (pycodestyle errors)  | MEDIUM          |
| `F` (pyflakes errors)     | MEDIUM          |
| `W` (warnings)            | LOW             |
| `I` (import sorting)      | LOW             |
| `N` (naming conventions)  | LOW             |
| All other prefixes        | LOW             |

#### PMD — Linting rules (Java)

| PMD Priority | Mapped Severity |
| ------------ | --------------- |
| 1            | MEDIUM          |
| 2            | MEDIUM          |
| 3            | MEDIUM          |
| 4            | LOW             |
| 5            | INFO            |

PMD covers linting, complexity, and dead code — all non-security categories. The PMD priority 1-5 scale is compressed to cap at MEDIUM.

### 2.3 Type Safety Tools (capped at MEDIUM)

#### javac (Java)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| `error`              | MEDIUM          |
| `warning`            | LOW             |

#### mypy (Python)

| Tool-Native Severity | Mapped Severity |
| -------------------- | --------------- |
| `error`              | MEDIUM          |
| `warning`            | LOW             |
| `note`               | INFO            |

Consistent across both languages for the type safety category.

### 2.4 Complexity Tools (capped at MEDIUM)

#### Radon (Python)

| Complexity Rank | Mapped Severity |
| --------------- | --------------- |
| A (1-5)         | INFO            |
| B (6-10)        | LOW             |
| C (11-15)       | MEDIUM          |
| D (16-20)       | MEDIUM          |
| E (21-25)       | MEDIUM          |
| F (26+)         | MEDIUM          |

#### PMD Complexity Rules (Java)

Uses the standard PMD priority mapping (capped at MEDIUM, see 2.2).

### 2.5 Code Duplication Tools (capped at MEDIUM)

#### PMD-CPD (Java)

| Condition                      | Mapped Severity |
| ------------------------------ | --------------- |
| Duplicated block < 30 lines    | LOW             |
| Duplicated block >= 30 lines   | MEDIUM          |

Python duplication tool (jscpd) is not yet implemented.

### 2.6 Dead Code Tools (capped at MEDIUM)

#### Vulture (Python)

| Condition            | Mapped Severity |
| -------------------- | --------------- |
| Confidence >= 80%    | MEDIUM          |
| Confidence < 80%     | LOW             |

#### PMD Dead Code Rules (Java)

Uses the standard PMD priority mapping (capped at MEDIUM, see 2.2).

---

## 3. Verdict Logic

Source: `common/report.py` — `_overall_verdict()`

The overall verdict is determined by counting findings across ALL tools:

```text
if CRITICAL > 0  OR  HIGH >= 5   -->  "Critical"
if HIGH > 0      OR  MEDIUM >= 10 -->  "Needs Attention"
otherwise                          -->  "Good"
```

Because HIGH/CRITICAL are reserved for security, this means:

- **"Critical"** can only be triggered by security findings (CRITICAL vulnerabilities or 5+ HIGH security issues)
- **"Needs Attention"** is triggered by any security finding (1+ HIGH) or by 10+ non-security issues at MEDIUM
- **"Good"** means no security findings and fewer than 10 medium-severity non-security issues

This is intentional — security issues are non-negotiable and immediately escalate the verdict.

---

## 4. Top Findings Selection

Source: `common/report.py` — `_top_findings()`

The executive summary "Top Findings" section uses this algorithm:

1. **Include ALL CRITICAL and HIGH findings** — these are security issues and are not capped or hidden
2. Deduplicate by `rule_id:file` so repeated hits don't dominate
3. Fill remaining slots (up to 5 by default) with MEDIUM findings, round-robin across categories for diversity
4. LOW and INFO findings are not shown in the top findings

This means: if there are 12 HIGH security findings, all 12 appear in the top findings. Security is non-negotiable and fully visible in the executive summary.

All findings (including LOW and INFO) are still reported in full in the per-tool sections (Section 3.x of the report).

---

## 5. Quick Reference Table

| Tool       | Language | Category                     | Native Value      | Mapped Severity |
| ---------- | -------- | ---------------------------- | ----------------- | --------------- |
| semgrep    | Both     | security                     | ERROR             | HIGH            |
| semgrep    | Both     | security                     | WARNING           | MEDIUM          |
| semgrep    | Both     | security                     | INFO              | LOW             |
| gitleaks   | Both     | security                     | (all secrets)     | HIGH            |
| bandit     | Python   | security                     | HIGH              | HIGH            |
| bandit     | Python   | security                     | MEDIUM            | MEDIUM          |
| bandit     | Python   | security                     | LOW               | LOW             |
| checkstyle | Java     | linting                      | error             | MEDIUM          |
| checkstyle | Java     | linting                      | warning           | LOW             |
| checkstyle | Java     | linting                      | info              | INFO            |
| ruff       | Python   | linting                      | E/F prefix        | MEDIUM          |
| ruff       | Python   | linting                      | W/I/N prefix      | LOW             |
| pmd        | Java     | linting/complexity/dead_code | priority 1-3      | MEDIUM          |
| pmd        | Java     | linting/complexity/dead_code | priority 4        | LOW             |
| pmd        | Java     | linting/complexity/dead_code | priority 5        | INFO            |
| javac      | Java     | type_safety                  | error             | MEDIUM          |
| javac      | Java     | type_safety                  | warning           | LOW             |
| mypy       | Python   | type_safety                  | error             | MEDIUM          |
| mypy       | Python   | type_safety                  | warning           | LOW             |
| mypy       | Python   | type_safety                  | note              | INFO            |
| radon      | Python   | complexity                   | A                 | INFO            |
| radon      | Python   | complexity                   | B                 | LOW             |
| radon      | Python   | complexity                   | C-F               | MEDIUM          |
| pmd-cpd    | Java     | duplication                  | < 30 lines        | LOW             |
| pmd-cpd    | Java     | duplication                  | >= 30 lines       | MEDIUM          |
| vulture    | Python   | dead_code                    | >= 80% confidence | MEDIUM          |
| vulture    | Python   | dead_code                    | < 80% confidence  | LOW             |
