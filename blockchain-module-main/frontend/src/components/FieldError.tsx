// src/components/FieldError.tsx
// The red error line under an invalid field — pair with
// `lib/validation.ts`'s `errorInputClass` on the field itself. Renders
// nothing when there's no error, so it's always safe to include.
const FieldError = ({ message }: { message?: string | null }) => {
  if (!message) return null;
  return <p className="text-destructive text-xs mt-1">{message}</p>;
};

export default FieldError;
