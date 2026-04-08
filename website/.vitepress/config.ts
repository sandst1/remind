import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Remind',
  description: 'Generalization-capable memory layer for LLMs',
  base: '/remind/',
  head: [
    ['meta', { property: 'og:title', content: 'Remind' }],
    ['meta', { property: 'og:description', content: 'Make AI dream about your tokens.' }],
  ],

  themeConfig: {
    nav: [
      { text: 'Guide', link: '/guide/what-is-remind' },
      { text: 'Concepts', link: '/concepts/episodes' },
      { text: 'Examples', link: '/examples/' },
      { text: 'Reference', link: '/reference/cli-commands' },
      {
        text: 'v0.10.2',
        items: [
          { text: 'Changelog', link: '/reference/changelog' },
          { text: 'PyPI', link: 'https://pypi.org/project/remind-mcp/' },
        ],
      },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Introduction',
          items: [
            { text: 'What is Remind?', link: '/guide/what-is-remind' },
            { text: 'Getting Started', link: '/guide/getting-started' },
            { text: 'Configuration', link: '/guide/configuration' },
          ],
        },
        {
          text: 'Integration',
          items: [
            { text: 'Skills + CLI', link: '/guide/skills' },
            { text: 'MCP Server', link: '/guide/mcp' },
            { text: 'Web UI', link: '/guide/web-ui' },
            { text: 'Python API', link: '/guide/python-api' },
          ],
        },
      ],
      '/concepts/': [
        {
          text: 'Core Concepts',
          items: [
            { text: 'Episodes', link: '/concepts/episodes' },
            { text: 'Consolidation', link: '/concepts/consolidation' },
            { text: 'Concepts', link: '/concepts/concepts' },
            { text: 'Entities', link: '/concepts/entities' },
            { text: 'Relations', link: '/concepts/relations' },
            { text: 'Retrieval', link: '/concepts/retrieval' },
            { text: 'Auto-Ingest', link: '/concepts/auto-ingest' },
            { text: 'Memory Decay', link: '/concepts/memory-decay' },
            { text: 'Tasks', link: '/concepts/tasks' },
          ],
        },
      ],
      '/examples/': [
        {
          text: 'Examples',
          items: [
            { text: 'Overview', link: '/examples/' },
            { text: 'Project Memory', link: '/examples/project-memory' },
            { text: 'Sparring Partner', link: '/examples/sparring-partner' },
            { text: 'Research Ingestion', link: '/examples/research-ingestion' },
          ],
        },
      ],
      '/reference/': [
        {
          text: 'Reference',
          items: [
            { text: 'CLI Commands', link: '/reference/cli-commands' },
            { text: 'MCP Tools', link: '/reference/mcp-tools' },
            { text: 'REST API', link: '/reference/rest-api' },
            { text: 'Providers', link: '/reference/providers' },
            { text: 'Changelog', link: '/reference/changelog' },
          ],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/sandst1/remind' },
    ],

    search: {
      provider: 'local',
    },

    footer: {
      message: 'Released under the Apache 2.0 License.',
    },
  },
})
