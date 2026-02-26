import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const inputVariants = cva(
  'flex w-full rounded-md border border-border bg-secondary text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-50 transition-colors',
  {
    variants: {
      inputSize: {
        default: 'h-10 px-3 py-2 text-sm',
        compact: 'h-[30px] px-3 py-1 text-[12px]',
        sm: 'h-6 px-2 py-0.5 text-xs',
      },
    },
    defaultVariants: {
      inputSize: 'default',
    },
  },
)

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement>, VariantProps<typeof inputVariants> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, inputSize, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(inputVariants({ inputSize, className }))}
        ref={ref}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'

// eslint-disable-next-line react-refresh/only-export-components -- CVA variant intentionally co-exported
export { Input, inputVariants }
