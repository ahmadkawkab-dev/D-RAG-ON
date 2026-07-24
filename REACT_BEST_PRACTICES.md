# React Frontend — Code Review Checklist

> **Purpose:** This document defines the best-practice standards a coding agent (or human reviewer) should check a React codebase against. Review the target repository section by section and flag any deviation, explaining *why* it deviates and *how* to fix it.

---

## 1. Project Structure

- [ ] Source code lives under `src/`, not scattered at the repo root.
- [ ] Structure follows a clear organizing principle — either:
  - **Type-based** (`components/`, `hooks/`, `pages/`, `services/`, `utils/`, `context/`, `store/`) for smaller apps, or
  - **Feature/domain-based** (`features/auth/`, `features/checkout/`, each containing its own `components/`, `hooks/`, `api/`, `tests/`) for larger apps.
- [ ] No mixing of both styles inconsistently across the codebase — pick one and apply it uniformly.
- [ ] Shared/reusable code lives in a common location (`src/shared/` or `src/common/`), separate from feature-specific code.
- [ ] Static assets (images, fonts, icons) are organized under `src/assets/` or `public/`, not inline-duplicated across folders.
- [ ] Path aliases (e.g. `@components`, `@utils`) are configured (via `tsconfig.json`/`jsconfig.json` or bundler config) to avoid deep relative imports like `../../../../utils`.
- [ ] Environment-specific config (`.env`, `.env.local`, `.env.production`) is present and **not** committed with real secrets.

---

## 2. Component Design

- [ ] Components are **function components** using hooks — no legacy class components unless justified (e.g. error boundaries).
- [ ] Each component file exports **one primary component**; file name matches component name (`UserCard.jsx` → `UserCard`).
- [ ] Components follow **single-responsibility**: presentational ("dumb") components are separated from container/logic-holding components where complexity warrants it.
- [ ] No component file exceeds ~200–300 lines without a clear justification; large components should be decomposed.
- [ ] Props are destructured in the function signature, not accessed via `props.x` throughout the body.
- [ ] Default props are handled via default parameter values, not `defaultProps` (deprecated for function components in modern React).
- [ ] Components avoid deeply nested ternaries/conditionals in JSX — extract to variables or small subcomponents.
- [ ] No business logic embedded directly in JSX render — logic is extracted into functions, hooks, or helpers above the return statement.

---

## 3. Hooks

- [ ] Hooks are only called at the top level of components/hooks — never inside loops, conditions, or nested functions (Rules of Hooks).
- [ ] Custom hooks are prefixed with `use` and extracted when logic is reused across components or when a component's logic becomes complex.
- [ ] `useEffect` dependency arrays are complete and accurate — no suppressed `eslint-disable-line react-hooks/exhaustive-deps` without a documented reason.
- [ ] Effects that subscribe/add listeners/timers include a cleanup function.
- [ ] `useState` is not used for values that could be derived during render (avoid redundant state that must be kept in sync).
- [ ] `useMemo`/`useCallback` are used deliberately for expensive computations or to stabilize references passed to memoized children — not applied reflexively everywhere.
- [ ] No direct DOM manipulation via `document.querySelector` etc. where a `ref` would be idiomatic.

---

## 4. State Management

- [ ] Local component state (`useState`/`useReducer`) is used for UI-only state; global state is reserved for data genuinely shared across distant parts of the tree.
- [ ] If a global store is used (Redux, Zustand, Jotai, Context, etc.), there is **one** consistent solution — not multiple competing patterns for the same kind of state.
- [ ] Context providers are scoped as narrowly as possible to avoid unnecessary re-renders of unrelated components.
- [ ] Server/remote data uses a dedicated data-fetching layer (React Query, SWR, RTK Query) rather than manual `useEffect` + `useState` fetch boilerplate repeated across components, unless the project deliberately avoids that dependency.
- [ ] No prop drilling beyond 2–3 levels — deeper sharing should go through context or a store.

---

## 5. Routing

- [ ] Routing is centralized (e.g. a single `routes.jsx`/`AppRouter.jsx`), not scattered `<Route>` declarations across files.
- [ ] Route-level components are **code-split** with `React.lazy` + `Suspense` for larger apps.
- [ ] Protected/auth-gated routes use a consistent guard pattern (wrapper component or route config flag), not ad-hoc checks per page.
- [ ] 404 / fallback routes are defined.

---

## 6. Styling

- [ ] One consistent styling approach across the app (CSS Modules, Tailwind, styled-components, vanilla-extract, Sass, etc.) — not several competing systems introduced ad hoc.
- [ ] Global styles/resets are isolated to a single entry point (`index.css`/`globals.css`), not duplicated per component.
- [ ] No excessive inline `style={{}}` usage for static styling that belongs in a stylesheet.
- [ ] Design tokens (colors, spacing, typography) are centralized (theme file, CSS variables, Tailwind config) rather than magic values repeated throughout.

---

## 7. TypeScript / Type Safety (if applicable)

- [ ] `strict` mode is enabled in `tsconfig.json`.
- [ ] Props, state, and API response shapes are explicitly typed/interfaced — no unchecked `any` for structured data.
- [ ] Shared types live in a common `types/` directory or colocated with the domain they describe, not duplicated across files.
- [ ] API responses are validated or typed at the boundary (e.g. via generated types, Zod/io-ts schemas), not trusted blindly as `any`.

---

## 8. API / Data Layer

- [ ] API calls are abstracted into a service layer (`src/api/`, `src/services/`) — components do not call `fetch`/`axios` directly inline.
- [ ] A single HTTP client instance/config (base URL, interceptors, auth headers) is reused, not reinstantiated per call.
- [ ] Loading, error, and empty states are explicitly handled for every async data fetch — no silent failures or unhandled promise rejections.
- [ ] Sensitive tokens are not stored in `localStorage` when a more secure option (httpOnly cookies) is feasible; if `localStorage`/`sessionStorage` is used, this is a deliberate, documented tradeoff.

---

## 9. Error Handling

- [ ] At least one top-level **Error Boundary** wraps the app (or major sections) to catch render errors gracefully.
- [ ] Async errors (fetch failures, rejected promises) are caught and surfaced to the user, not just logged to console.
- [ ] User-facing error messages are meaningful, not raw stack traces or generic "Something went wrong" with no recovery path.

---

## 10. Performance

- [ ] Lists render with stable, unique `key` props — never array index as key for dynamic/reorderable lists.
- [ ] Large lists use virtualization (e.g. `react-window`) when rendering hundreds+ of items.
- [ ] Images use appropriate sizing/lazy-loading (`loading="lazy"`, responsive `srcSet`) rather than full-resolution assets everywhere.
- [ ] Unnecessary re-renders are avoided: components aren't re-created inline unnecessarily (e.g. new function/object literals passed as props to memoized children without `useCallback`/`useMemo` where it matters).
- [ ] Bundle is code-split at route/feature boundaries; no single monolithic bundle for a non-trivial app.

---

## 11. Accessibility (a11y)

- [ ] Semantic HTML elements are used (`<button>`, `<nav>`, `<main>`, `<header>`) instead of `<div onClick>` for interactive elements.
- [ ] Images have meaningful `alt` text (or `alt=""` when purely decorative).
- [ ] Form inputs have associated `<label>`s.
- [ ] Interactive elements are keyboard-navigable and have visible focus states.
- [ ] Color contrast meets WCAG AA at minimum for text content.

---

## 12. Testing

- [ ] Unit/component tests exist (Jest/Vitest + React Testing Library), colocated with components (`Component.test.jsx`) or under a mirrored `__tests__/` structure.
- [ ] Tests query the DOM the way a user would (`getByRole`, `getByLabelText`) rather than implementation details (`getByTestId` overused, class-name selectors).
- [ ] Critical user flows have at least basic integration or E2E coverage (Playwright/Cypress), not only unit tests on isolated pieces.
- [ ] No tests are skipped/disabled without a tracked reason (e.g. linked issue).

---

## 13. Code Quality & Tooling

- [ ] ESLint is configured with a React-appropriate ruleset (`eslint-plugin-react`, `eslint-plugin-react-hooks`) and passes with no unresolved errors.
- [ ] Prettier (or equivalent) enforces consistent formatting; no mixed formatting styles across files.
- [ ] No commented-out dead code, leftover `console.log` debugging statements, or unused imports/variables left in the codebase.
- [ ] Naming conventions are consistent: `PascalCase` for components, `camelCase` for functions/variables, `UPPER_SNAKE_CASE` for true constants.
- [ ] No circular imports between modules.

---

## 14. Security

- [ ] No use of `dangerouslySetInnerHTML` without sanitization (e.g. DOMPurify) of the injected content.
- [ ] No secrets (API keys, tokens) hardcoded in source — all pulled from environment variables and excluded via `.gitignore`.
- [ ] Third-party dependencies are reasonably current, with no known critical vulnerabilities left unaddressed (check `npm audit`/`yarn audit` output if available).
- [ ] User input is validated/sanitized before being rendered or sent to an API.

---

## Review Output Format

When reviewing a codebase against this checklist, the agent should report findings as:

```
### [Category] Issue Title
- **Location:** path/to/file.jsx:line
- **Violation:** Which checklist item this breaks
- **Why it matters:** Brief impact explanation
- **Suggested fix:** Concrete remediation
```

Group findings by severity where possible:
- **Critical** — security issues, broken functionality, accessibility blockers
- **Major** — architectural inconsistencies, missing error handling, performance problems
- **Minor** — style/naming inconsistencies, missing tests, cleanup items
