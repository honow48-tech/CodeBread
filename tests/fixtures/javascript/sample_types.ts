// Sample TypeScript file — checks type annotations don't break extraction.
interface User {
  id: number;
  name: string;
}

function getUserName(user: User): string {
  return user.name;
}

const double = (n: number): number => n * 2;

export class Greeter {
  greet(name: string): string {
    return `Hello, ${name}`;
  }
}
