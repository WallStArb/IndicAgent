# IndicAgent Documentation Standards

**Version:** 2.1.0
**Last Updated:** 2026-02-12
**Status:** Current - Intelligence-First Standards

## File Naming Conventions

### **Standard Files (Keep Uppercase)**
- `README.md` - Directory/project overview
- `CHANGELOG.md` - Version change history  
- `LICENSE` - License information (no .md extension)
- `CONTRIBUTING.md` - Contribution guidelines

### **Documentation Files (Use kebab-case)**
Based on 2024 best practices, all documentation files use lowercase with hyphens:

**Correct:**
- `ai-intelligence-architecture.md`
- `market-intelligence-strategy.md`
- `plugin-registry-and-dag-execution.md`

**Incorrect:**
- `AI_INTELLIGENCE_ARCHITECTURE.md`
- `MARKET_INTELLIGENCE_STRATEGY.md`
- `Plugin_Registry_And_DAG_Execution.md`

### **Directory Naming**
- Use lowercase with hyphens: `intelligence/`, `architecture/`, `configuration/`
- Avoid underscores or spaces in directory names

## Content Standards

### **Document Headers (Enhanced)**
All documentation files must include:
```markdown
# Document Title

**Version:** X.Y.Z  
**Last Updated:** YYYY-MM-DD  
**Status:** Current/Archive/Draft - [Brief Status Description]
**Purpose:** [Brief description for intelligence/planning documents]
```

**Status Examples:**
- `Current - Enhanced with LangGraph Architecture`
- `Current - Comprehensive Enhancement Complete`
- `Current - Aligned with Pattern Detection Sprint`
- `Archive - Superseded by [replacement document]`
- `Development - Active Implementation Phase`

### **Section Organization (Intelligence-Focused)**
**For Intelligence & Planning Documents:**
1. **Executive Summary/Purpose** - Intelligence transformation goals and document scope
2. **Current State** - What exists now (services, agents, capabilities)
3. **Target State/Vision** - Progressive intelligence evolution path
4. **Implementation Strategy** - CRL progression, development phases, timeline
5. **Success Metrics** - Measurable outcomes and performance targets
6. **References** - Links to related documents and architecture

**For Technical Documents:**
1. **Overview** - Technical scope and integration points
2. **Current Implementation** - What's operational and performance characteristics
3. **Architecture/Design** - Technical specifications and patterns
4. **Integration Examples** - Code examples and usage patterns
5. **Next Steps** - Development priorities and enhancements

### **Cross-References**
- Use relative paths: `[Architecture](architecture/layered-architecture.md)`
- Always test links after reorganization
- Update navigation files when adding/moving documents

## Language and Tone Standards

### **Intelligence-First Language (Updated)**
**Preferred Intelligence Terminology:**
- **"Intelligence extraction"** → "Pattern intelligence", "Market intelligence", "AI-powered analysis"
- **"Progressive intelligence layers"** → I1 (mathematical) → I2-I4 (composite) → I5-I7 (patterns) → I8 (AI synthesis)
- **"Configuration-driven pipelines"** → YAML-based intelligence composition, plugin framework integration
- **"Event-driven workflows"** → LangGraph workflows, circuit breaker patterns, enhanced monitoring
- **"Risk-first intelligence"** → Capital preservation analysis, pattern failure probability

**Avoid Trading-Centric Language:**
- **Avoid:** "Trading signals", "Trade execution", "Strategy backtesting"
- **Use Instead:** "Intelligence insights", "Pattern analysis", "Intelligence validation"

### **Current Architecture Terminology**
**LangGraph & Hybrid Architecture:**
- **"LangGraph event-driven workflows"** with enhanced monitoring and circuit breakers
- **"Hybrid service-plugin architecture"** maintaining 141x performance + plugin flexibility
- **"Conceptual Readiness Levels"** (CRL-1 through CRL-4) for development progression
- **"Intelligence tiers"** (I1-I8) for progressive intelligence classification

**AI Agent Framework:**
- **"46+ specialized AI agents"** organized into 8 intelligence categories (conceptual, for future I8)
- **"Multi-timeframe confluence"** analysis across 1m→5m→15m→1h→4h→1d

### **Technical Precision (Enhanced)**
- Use **intelligence tier classifications** (I1-I8) consistently
- Reference **current architecture components** (LangGraph, hybrid service-plugin, DragonflyDB)
- Include **performance metrics** (141x speedup, >75% pattern accuracy, <5 second processing)
- Define **futures-specific terminology** (ES/NQ/RTY, institutional flow, market structure)

### **Clarity and Conciseness (Updated)**
- Start with **intelligence transformation goals** for complex topics
- Use **progressive intelligence examples** (basic indicators → institutional-grade analysis)
- Include **current development status** and realistic timelines
- Reference **existing documentation** using relative paths

## Visual Organization Standards

### **Professional Formatting**
Maintain professional appearance through consistent formatting:

**Status Indicators (Text-Based):**
- **OPERATIONAL:** Complete and functioning components
- **DEVELOPMENT:** Components actively being developed  
- **PLANNED:** Architected components ready for implementation
- **DEPRECATED:** Outdated or replaced components

**Section Organization:**
- Use clear, descriptive headers without decorative elements
- Maintain consistent capitalization and punctuation
- Use bullet points and numbered lists for clarity
- Include code blocks for technical specifications

### **Header Hierarchy Standards**
```markdown
# Document Title
## Major Section
### Subsection  
#### Technical Detail
```

### **Professional Language Guidelines**
- Use clear, technical language appropriate for enterprise documentation
- Avoid casual expressions, internet slang, or decorative elements
- Focus on precision and clarity over visual appeal
- Maintain consistent terminology throughout documentation

## Maintenance Standards

### **Version Control**
- Update version numbers for significant changes
- Document change rationale in commit messages
- Archive outdated documents rather than deleting

### **Link Maintenance**
- Verify all internal links after document moves
- Update navigation files immediately
- Test external links periodically

### **Content Quality**
- Review for accuracy after technical changes
- Ensure examples match current implementation
- Keep implementation details current with codebase

## Directory Structure Standards (Updated)

```
/docs/
├── README.md                          # Main navigation (standard uppercase)
├── documentation-standards.md         # This file (kebab-case)
├── intelligence-platform-overview.md  # Core documents (kebab-case)
├── development-roadmap.md            # Core documents (kebab-case)
├── current-status-and-priorities.md   # Current development focus
├── documentation-audit.md            # README/CLAUDE/docs alignment audit
├── architecture/                     # Technical architecture
│   ├── layered-architecture.md       # Overall system architecture
│   ├── intelligence-tiers.md         # I1-I8 intelligence classification
│   ├── plugin-registry-and-dag-execution.md # Plugin framework and DAG engine
│   ├── event-driven-indicator-system.md # LangGraph workflow processing
│   ├── comprehensive-intelligence-architecture.md # Complete hybrid blueprint
│   ├── plugin-native-architecture-explained.md # Conceptual guide
│   └── stream-schemas.md            # Redis stream data contracts
├── planning/                         # Historical planning documents (Aug 2025)
│   ├── ideas/                        # Concepts and research
│   └── _archive/                     # Superseded planning documents
├── intelligence/                     # AI intelligence framework docs
│   ├── ai-intelligence-architecture.md
│   └── ai-intelligence-resources.md
├── configuration/                    # Data source configuration
└── _archive/                         # Historical preservation
```

## Migration Strategy

### **Phase 1: Standardize Existing Files**
1. Rename all non-standard files to kebab-case
2. Update all cross-references and navigation
3. Test all links and fix broken references

### **Phase 2: Update Cross-References**
1. Update main `README.md` navigation
2. Update `planning/README.md` references
3. Update any inline links in content

### **Phase 3: Documentation**
1. Create/update navigation files
2. Document the new standards
3. Archive old naming conventions

## Benefits of These Standards

### **Technical Benefits**
- **Cross-platform compatibility** - Works on all file systems
- **Web-friendly URLs** - No case sensitivity issues
- **Package compatibility** - Follows npm/package naming standards
- **Modern tooling support** - Works with all modern documentation tools

### **Team Benefits**
- **Consistent naming** reduces cognitive load
- **Predictable structure** improves navigation
- **Version tracking** enables change management
- **Clear standards** reduce decision fatigue

### **Maintenance Benefits**
- **Automated link checking** easier with consistent patterns
- **Search and replace** operations more reliable
- **Tool integration** works better with standard conventions
- **Archive management** clearer with consistent structure

## Review and Updates

These standards should be reviewed annually or when major documentation reorganizations occur. All team members should follow these standards for new documentation and gradually migrate existing files during normal maintenance cycles.

---

## Intelligence Documentation Quality Standards

### **AI Agent Documentation Requirements**
- **Agent Concept**: Clear intelligence capabilities and unique value proposition
- **Integration Flow**: Data consumption → processing → intelligent output
- **Intelligence Tier**: Explicit I1-I8 classification
- **CRL Status**: Conceptual Readiness Level (CRL-1 through CRL-4)
- **Success Metrics**: Measurable performance targets and accuracy expectations

### **Architecture Documentation Requirements**
- **Current State**: What's operational with performance characteristics
- **Technology Stack**: LangGraph, hybrid service-plugin, DragonflyDB, TimescaleDB
- **Performance Metrics**: Specific numbers (141x speedup, <5 second processing, >75% accuracy)
- **Integration Points**: How components connect and data flows
- **Next Steps**: Clear development progression and priorities

### **Planning Documentation Requirements**
- **Progressive Intelligence Vision**: Transformation from basic indicators to institutional-grade analysis
- **Realistic Timelines**: Based on current capabilities and development velocity
- **Phase Boundaries**: Clear progression gates and success criteria
- **Architecture Alignment**: Integration with current LangGraph and hybrid approach

---

**Adoption Date:** 2025-08-17
**Last Revised:** 2026-02-12
**Standards Based On:** Intelligence-first development approach, LangGraph architecture, plugin-native processing