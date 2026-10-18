import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-40',
  {
    variants: {
      variant: {
        // Amber — the one strong CTA. Use sparingly. Windows High Contrast drops the fill, so
        // filled variants get an outline there to still read as buttons.
        default: 'bg-primary text-primary-foreground hover:bg-primary/85 forced-colors:border',
        destructive:
          'bg-destructive/10 text-destructive border border-destructive/30 hover:bg-destructive/15',
        outline:
          'border border-border bg-transparent text-foreground hover:bg-secondary hover:border-border/70',
        secondary: 'bg-secondary text-foreground hover:bg-secondary/70 forced-colors:border',
        ghost: 'text-muted-foreground hover:bg-secondary hover:text-foreground',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-12 rounded-md px-8',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    )
  },
)
Button.displayName = 'Button'

// eslint-disable-next-line react-refresh/only-export-components -- CVA variant intentionally co-exported
export { Button, buttonVariants }
