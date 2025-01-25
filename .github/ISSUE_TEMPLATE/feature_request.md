---
name: Feature request
about: Suggest an idea for SpotifyDownloader
title: '[FEATURE] '
labels: enhancement
assignees: 2Friendly4You
description: File a feature request
body:
  - type: dropdown
    id: feature_type
    attributes:
      label: Feature Type
      description: What type of feature are you suggesting?
      options:
        - UI/UX Improvement
        - New Download Option
        - Performance Enhancement
        - Integration with Other Services
        - Other
    validations:
      required: true

  - type: textarea
    id: problem_description
    attributes:
      label: Is your feature request related to a problem?
      description: A clear and concise description of what the problem is.
      placeholder: I'm always frustrated when [...]
    validations:
      required: true

  - type: textarea
    id: solution_description
    attributes:
      label: Describe the solution you'd like
      description: A clear and concise description of what you want to happen.
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Describe alternatives you've considered
      description: A clear and concise description of any alternative solutions or features you've considered.
    validations:
      required: false

  - type: dropdown
    id: priority
    attributes:
      label: Priority Level
      description: How important is this feature to you?
      options:
        - Critical
        - High
        - Medium
        - Low
        - Nice to have
    validations:
      required: true

  - type: textarea
    id: additional_context
    attributes:
      label: Additional context
      description: Add any other context or screenshots about the feature request here.
    validations:
      required: false
---
---
name: Feature request
about: Suggest an idea for SpotifyDownloader
title: '[FEATURE] '
labels: enhancement
assignees: 2Friendly4You
---

**Is your feature request related to a problem? Please describe.**
A clear and concise description of what the problem is. Ex. I'm always frustrated when [...]

**Describe the solution you'd like**
A clear and concise description of what you want to happen.

**Describe alternatives you've considered**
A clear and concise description of any alternative solutions or features you've considered.

**Additional context**
Add any other context or screenshots about the feature request here.
