import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import ConfirmDialog from './ConfirmDialog'

const meta: Meta<typeof ConfirmDialog> = {
  title: 'Common/ConfirmDialog',
  component: ConfirmDialog,
  args: {
    onConfirm: fn(),
    onCancel: fn(),
  },
}

export default meta
type Story = StoryObj<typeof ConfirmDialog>

export const DeletePosition: Story = {
  args: {
    open: true,
    title: 'Delete position',
    body: 'Delete this position? This cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    destructive: true,
  },
}

export const GenericConfirm: Story = {
  args: {
    open: true,
    title: 'Discard changes?',
    body: 'You have unsaved changes. Discard them?',
    confirmLabel: 'Discard',
    cancelLabel: 'Keep editing',
  },
}
