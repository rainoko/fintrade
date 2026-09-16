import type { StorybookConfig } from '@storybook/react-vite'

const config: StorybookConfig = {
  stories: ['../src/**/*.mdx', '../src/**/*.stories.@(ts|tsx)'],
  // Frontend.md §4: components/common/ is the catalog Storybook covers;
  // addon-a11y is the required accessibility addon (task checklist),
  // addon-docs gives every story an auto-generated docs page for free.
  addons: ['@storybook/addon-a11y', '@storybook/addon-docs'],
  framework: '@storybook/react-vite',
}

export default config
