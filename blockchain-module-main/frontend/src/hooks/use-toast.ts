export const useToast = () => {
  return {
    toast: (opts: any) => {
      console.log("TOAST:", opts.title, opts.description);
      alert(`${opts.title}\n${opts.description || ''}`);
    }
  }
}
