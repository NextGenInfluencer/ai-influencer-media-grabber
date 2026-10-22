# Workspace Rules & Preferences

## 1. Code Quality & Standards
- **Clean Code**: Always write clean, maintainable, robust, and well-structured code.
- **Modern Libraries Only**: Strictly avoid using deprecated libraries, functions, or patterns. Use modern, actively supported APIs.
- **Maintain Test Integrity**: All changes must preserve 100% test coverage and ensure unit and integration test suites pass completely.
- **Preserve User Projects & Data**: Never modify, corrupt, or delete user media, caption projects, or credentials.

## 2. UI / UX Design System (Apple / macOS Pro Standard)
- **Aesthetic**: All user interfaces must look and feel clean, modern, elegant, and polished—emulating Apple macOS and Pro creative software (e.g., Final Cut Pro, CapCut desktop).
- **Visual Design**:
  - Typography: SF Pro style (`-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif`), clear hierarchy, crisp font weights.
  - Materials & Depth: Frosted glass surfaces (`backdrop-filter: blur(24px)` to `blur(32px)`), subtle translucent borders (`rgba(255, 255, 255, 0.08)` to `0.15`), and soft elevated drop shadows.
  - Color Palette: Apple System Blue (`#0071e3` / `#0a84ff`) for primary actions, vivid system accents (pink, teal, purple) for badges/states, deep neutral obsidian backgrounds (`#0a0b10` to `#161822`).
- **User Experience & Interactions**:
  - **Intuitive & Effortless**: Provide 1-click shortcuts for frequent workflows (e.g., "📋 Paste URL" from clipboard, "📂 Open in Explorer" to reveal files directly).
  - **Immediate Feedback & Delight**: Real-time feedback for user actions (auto-detecting social media platforms, reactive badges, toast confirmations).
  - **High-Polished Empty States**: Never leave raw or plain-text empty states. Every view (gallery, history, queue) must feature an elegant card with icon, friendly guidance, and 1-click call-to-action buttons.
  - **Keyboard Accessibility**: Support pro-level keyboard shortcuts (`Space` to play/pause, `Ctrl+B` to split, `Ctrl+Z` to undo, `←/→` to frame step, `Delete` to remove) and expose an intuitive shortcuts reference modal.
  - **Clutter-Free Controls**: Clean controls with precise range sliders, segmented tab switchers, and zoom presets.
