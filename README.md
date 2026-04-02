# Code9
Code9 is a localized, AI-powered development environment designed to turn fragmented code snippets into fully functional, executable programs instantly. Using the MLX framework, it generates the necessary "scaffolding"—imports, mock data, and environment setup—around a user's original code without altering the source logic.

## Primary goal
The primary goal of Code9 is to eliminate "environment friction." Developers often find useful logic or algorithms online but lack the time to set up the dependencies or mock data required to see them in action. Code9 automates this setup process locally on Apple Silicon, ensuring privacy and speed.

## Target User
 - Students & Beginners: Who need to see how small logic blocks interact with a full environment.
 - Data Scientists/Researchers: Who want to quickly prototype a single function without building a full script.
 - Software Engineers: Looking for a "scratchpad" that intelligently handles boilerplate.

## Planned Features
 - Dual-Pane Visual Editor: A web-based UI where the user types in one pane and the "AI Scaffolding" appears in another.

 - MLX Local Inference: Integration with mlx-lm to run Coder-series models (like Qwen2.5-Coder) entirely offline.

 - Automated Dependency Injection: The AI identifies missing libraries and suggests the necessary import statements.

 - Smart Mocking: Automatic generation of dummy variables, objects, or dataframes needed for the snippet to execute.

 - One-Click Execution: A seamless "Run" button that merges the AI shell with the user code and displays output in a dedicated console.

## Breakdown of components
 - Locally run Apple MLX on Mac with use of small 1B-7B models able to run on relitivly low powered machines
 - Friendly UI with easy to use systems
 - File writing/rewriting

## Dificulties

The most significant technical hurdle will be Contextual Accuracy & Safety. 
1.  Logic Mapping: It is difficult to ensure the AI creates a shell that actually fits the user’s intent. For example, if a user writes print(data.mean()), the AI must correctly guess if data should be a NumPy array, a Pandas DataFrame, or a simple list. If it guesses wrong, the code will crash despite having a "shell."
2.  Sandbox Execution: Running AI-generated code is inherently risky. I will need to research how to execute the final script in a way that is isolated from my system's sensitive files, likely using a restricted Python environment or a containerized approach.
3.  Model Latency: Balancing the size of the MLX model (e.g., 3B vs 7B parameters) so that the "shell" is generated fast enough to feel like a real-time IDE, rather than a slow chat-bot.

## Code9 UML Mockup
![Code9 UML](https://github.com/LOGAN-bruh/Code9/blob/main/images/Code9UML.drawio.png)

## Code9 UI Mockup

![Code9 UI](https://github.com/LOGAN-bruh/Code9/blob/main/images/Untitled%20drawing.png)
