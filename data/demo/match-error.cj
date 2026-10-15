enum Choice { A | B }
func value(choice: Choice): Int64 {
    match (choice) {
        case A => 1
    }
}
main() { println(value(B)) }
