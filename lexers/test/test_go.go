//Go test file for lexer testing.
//This file contains various Go constructs to test syntax highlighting.

package main

import (
	"fmt"
	"math/rand"
	"time"
)

// Constants
const (
	StatusOK   = 200
	StatusErr  = 500
	maxUsers   = 1000
	pi         = 3.14159
	greeting   = "Hello, 世界"
	binary     = 0b101010
	octal      = 0o777
	hexValue   = 0xFF
)

// Variables
var (
	globalVar  int
	count      = 42
	message    string = "Global message"
	isActive   bool   = true
	values     []int
	dataMap    map[string]int
	userList   []*User
)

// Custom type
type User struct {
	ID        int
	Name      string
	Email     string
	CreatedAt time.Time
	active    bool
}

// Interface
type Notifier interface {
	Notify() error
	Send(message string) bool
}

// Function with multiple return values
func ProcessData(input string) (result int, err error) {
	if input == "" {
		return 0, fmt.Errorf("empty input")
	}
	
	// Simple loop
	sum := 0
	for i := 0; i < len(input); i++ {
		sum += int(input[i])
	}
	
	return sum, nil
}

// Method on struct
func (u *User) Activate() {
	u.active = true
	u.CreatedAt = time.Now()
}

// Main function
func main() {
	// Print statement
	fmt.Println("Starting application...")
	
	// If-else statement
	if len(os.Args) > 1 {
		fmt.Printf("Argument: %s\n", os.Args[1])
	} else {
		fmt.Println("No arguments provided")
	}
	
	// Switch statement
	switch time.Now().Weekday() {
	case time.Monday, time.Tuesday, time.Wednesday:
		fmt.Println("Weekday")
	case time.Saturday, time.Sunday:
		fmt.Println("Weekend")
	default:
		fmt.Println("Thursday or Friday")
	}
	
	// For loop (Go's only loop construct)
	for i := 0; i < 5; i++ {
		fmt.Printf("Iteration: %d\n", i)
		
		// Nested block
		if i%2 == 0 {
			continue // Skip even numbers
		}
		
		fmt.Printf("Odd number: %d\n", i)
	}
	
	// Range loop
	numbers := []int{1, 2, 3, 4, 5}
	for index, value := range numbers {
		fmt.Printf("Index: %d, Value: %d\n", index, value)
	}
	
	// Defer statement
	defer fmt.Println("Deferred execution")
	
	// Go routine and channel
	messages := make(chan string, 2)
	go func() {
		messages <- "Hello from goroutine"
		close(messages)
	}()
	
	// Receive from channel
	msg := <-messages
	fmt.Println(msg)
	
	// Short variable declaration
	name, age := "John Doe", 30
	
	// Type assertion
	var value interface{} = "some string"
	if str, ok := value.(string); ok {
		fmt.Printf("String value: %s\n", str)
	}
	
	// Blank identifier
	_, err := ProcessData("test")
	if err != nil {
		fmt.Printf("Error: %v\n", err)
	}
	
	// Composite literals
	user := &User{
		ID:       1,
		Name:     "Alice",
		Email:    "alice@example.com",
		CreatedAt: time.Now(),
		active:   true,
	}
	
	// Slice and map literals
	scores := []int{95, 87, 92, 88, 96}
	userScores := map[string]int{
		"Alice": 95,
		"Bob":   87,
	}
	
	// Print final values
	fmt.Printf("User: %+v\n", user)
	fmt.Printf("Scores: %v\n", scores)
	fmt.Printf("User scores: %v\n", userScores)
}

// Block comment
/*
   This is a multi-line comment
   describing package functionality.
   It spans multiple lines.
*/

// Line comment explaining function purpose
func helperFunction() {
	// Another line comment
	x := 1 /* inline comment */ + 2
	fmt.Println(x)
}

// Raw string literal
const sqlQuery = `
	SELECT *
	FROM users
	WHERE active = true
	ORDER BY created_at DESC
	LIMIT 10
`

// Error handling example
func divide(a, b float64) (float64, error) {
	if b == 0 {
		return 0, fmt.Errorf("division by zero")
	}
	return a / b, nil
}