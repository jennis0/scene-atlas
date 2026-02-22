import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2 py-0 text-[11px] font-medium leading-5 transition-colors',
  {
    variants: {
      variant: {
        // Amber — for primary highlights only
        default: 'border-primary/30 bg-primary/15 text-primary',
        secondary: 'border-transparent bg-secondary text-foreground/60',
        destructive: 'border-destructive/30 bg-destructive/15 text-destructive',
        outline: 'border-border/50 text-foreground/50',
      },
    },
    defaultVariants: {
      variant: 'outline',
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

// eslint-disable-next-line react-refresh/only-export-components -- CVA variant intentionally co-exported
export { Badge, badgeVariants }
