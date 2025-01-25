name: Bug report
about: Create a report to help improve SpotifyDownloader
title: '[BUG] '
labels: bug
assignees: 2Friendly4You
description: File a bug report
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to fill out this bug report!

  - type: textarea
    id: bug_description
    attributes:
      label: Describe the bug
      description: A clear and concise description of what the bug is.
    validations:
      required: true

  - type: textarea
    id: reproduction_steps
    attributes:
      label: Steps to reproduce
      description: How do you trigger this bug?
      placeholder: |
        1. Go to '...'
        2. Click on '....'
        3. Enter '....'
        4. See error
    validations:
      required: true

  - type: textarea
    id: expected_behavior
    attributes:
      label: Expected behavior
      description: A clear and concise description of what you expected to happen.
    validations:
      required: true

  - type: dropdown
    id: browsers
    attributes:
      label: Browser
      description: What browsers are you seeing the problem on?
      multiple: true
      options:
        - Firefox
        - Chrome
        - Safari
        - Microsoft Edge
        - Other
    validations:
      required: true

  - type: dropdown
    id: os
    attributes:
      label: Operating System
      description: What operating system are you using?
      options:
        - Windows
        - macOS
        - Linux
        - Other
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: Version
      description: What version of SpotifyDownloader are you running?
    validations:
      required: true

  - type: textarea
    id: screenshots
    attributes:
      label: Screenshots
      description: If applicable, add screenshots to help explain your problem.
    validations:
      required: false

  - type: textarea
    id: additional_context
    attributes:
      label: Additional context
      description: Add any other context about the problem here.
    validations:
      required: false

  - type: checkboxes
    id: terms
    attributes:
      label: Code of Conduct
      description: By submitting this issue, you agree to follow our rules
      options:
        - label: I have searched existing issues and this has not been reported yet
          required: true
        - label: I am running the latest version of SpotifyDownloader
          required: true
