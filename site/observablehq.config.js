export default {
  title: "Jev Opportunity Atlas",
  root: "src",
  base: process.env.ATLAS_SITE_BASE ?? "/",
  pages: [
    {name: "Findings", path: "/"},
    {name: "Evidence", path: "/evidence"},
    {name: "Method", path: "/method"},
  ],
  interpreters: {".py": ["uv", "run", "--quiet", "--project", "..", "python"]},
  style: "style.css",
};
