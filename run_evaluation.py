import os
import re
import copy
import argparse
import json
from tqdm import tqdm
from env.evaluator import evaluator_function_directed_graph

def try_eval(x):
    try:
        return eval(x)
    except:
        return x
    
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser()

    # Model settings
    parser.add_argument("--user_model", type=str, default=None,
                       help="Model to use for the user agent")
    parser.add_argument("--assistant_model", type=str, default="gpt-4o-mini",
                       help="Model to use for the assistant agent")
    
    # Evaluation settings
    parser.add_argument("--tool_call_mode", type=str, default="fc",
                       help="Tool call mode for the assistant model", choices=["fc", "act-only", "react"])
    parser.add_argument("--tool_list", type=str, default="oracle",
                        choices=["full", "oracle"], help="Tool list to use for the simulation, only use the tools that have been evaluated or full tool list")
    parser.add_argument("--shuffle_func", action="store_true",
                       help="Whether to shuffle assistant functions")
    parser.add_argument("--default_constraint_option", type=str, default="full",
                        choices=["full", "required"], help="Default dependency to use for the other unevaluated actions")
    parser.add_argument("--constraint_descr_format", type=str, default="structured",
                        choices=["old", "structured"], help="Constraint dependency description format")
    parser.add_argument("--num_run_per_interaction", type=int, default=1,
                       help="Number of interactions per task")
    parser.add_argument("--max_constraints", type=int, default=7,
                       help="Maximum number of constraints to evaluate as a group")
    parser.add_argument("--verbose", action="store_true",
                       help="Whether to print verbose output")
    
    # Data settings
    parser.add_argument("--output_dir", type=str, default="./output",
                       help="Output directory")
    parser.add_argument("--domain", type=str, default="bank",
                       choices=["bank", "online_market", "dmv", "healthcare", "library", "hotel", "university", "all"], help="Domain name")
    
    args = parser.parse_args()
    
    return args

def save_results(output_file, results, verbose=False):
    """
    Save results to a JSON file.
    
    Args:
        output_file (str): Path to the output file
        results (list): List of task simulation results to save
        verbose (bool): Whether to print saving status
    """
    try:
        # Add debug print before saving
        print(f"Saving {len(results)} results. First result has evaluations: {'evaluations' in results[0] if results else False}")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=4)

        if verbose:
            print(f"Results saved successfully to {output_file}")
    except Exception as e:
        print(f"Error saving results to {output_file}: {str(e)}")

def load_existing_results(output_file):
    """
    Load existing results from a JSON file or return empty list if file doesn't exist.
    
    Args:
        output_file (str): Path to the output file
        
    Returns:
        list: List of task simulation results
    """
    try:
        if os.path.exists(output_file):
            with open(output_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
                print(f"Loaded {len(results)} results from {output_file}")  # Add debug print
                return results
        else:
            print(f"File {output_file} does not exist!")
    except Exception as e:
        print(f"Error loading results from {output_file}: {str(e)}")
    return []

# Define sort key function for constraint groups
def constraint_group_sort_key(item, max_constraints):
    key = item[0]
    if key == f"{max_constraints}+":
        return max_constraints  # Make "10+" sort after 5
    return int(key)  # Convert other keys to integers
    
def main():
    """Main function to run the simulation."""
    args = parse_args()
    
    # Define domains to process
    domains_to_process = ["bank", "online_market", "dmv", "healthcare", "library", "hotel", "university"] \
        if args.domain == "all" else [args.domain]
    
    # Initialize combined results for all domains
    combined_results = {}
    
    for current_domain in domains_to_process:
        # Setup output path
        output_dir = f"{args.output_dir}/{current_domain}"
        new_output_dir = f"{args.output_dir}/{current_domain}"
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(new_output_dir, exist_ok=True)
        output_file = os.path.join(
            output_dir,
            (f"usr_{args.user_model.replace('/', '_')}-" if args.user_model else "") + \
            f"ast_{args.assistant_model.replace('/', '_')}-" + \
            f"mode_{args.tool_call_mode}-" + \
            f"dep_{args.default_constraint_option}-" + \
            f"fmt_{args.constraint_descr_format}-" + \
            f"tool_{args.tool_list}-" + \
            f"shuffle_{args.shuffle_func}.json"
        )
        new_output_file = os.path.join(
            new_output_dir,
            (f"usr_{args.user_model.replace('/', '_')}-" if args.user_model else "") + \
            f"ast_{args.assistant_model.replace('/', '_')}-" + \
            f"mode_{args.tool_call_mode}-" + \
            f"dep_{args.default_constraint_option}-" + \
            f"fmt_{args.constraint_descr_format}-" + \
            f"tool_{args.tool_list}-" + \
            f"shuffle_{args.shuffle_func}.json"
        )

        print_results = {
            "user_model": args.user_model,
            "assistant_model": args.assistant_model,
            "domain": current_domain,
            "total_tasks": 0,
            "total_interactions": 0,
            "total_success": 0,
            "avg_num_messages": 0,
            "avg_num_function_calls": 0,
            "avg_num_constraints": 0,
            "avg_num_constraints_expanded": 0,
            "goal_statistics": {},
            "constraint_group_statistics": {},  # Group by constraint count
            "error_statistics": {              # Modified error tracking
                "total_evaluations": 0,
                "total_failures": 0,           
                "error_causes": {
                    "tool_call_errors": 0,            # Changed from no_tool_call_error
                    "constraint_violations": 0,        # Changed from constraint_not_violated
                    "database_mismatches": 0,          # Changed from database_match
                    "dirgraph_violations": 0,          # Changed from dirgraph_satisfied
                    "incorrect_action_calls": 0        # Changed from action_called_correctly
                },
                "outcome_categories": {
                    "outcome_correct_procedure_wrong": 0,  # Only dirgraph_violations error
                    "outcome_wrong_procedure_wrong": 0,    # Both dirgraph_violations AND (database_mismatches OR incorrect_action_calls)
                    "outcome_wrong_procedure_correct": 0,  # No dirgraph_violations BUT (database_mismatches OR incorrect_action_calls)
                    "outcome_correct_procedure_correct": 0 # All three metrics are correct
                }
            },
            "constraint_relation_group_statistics": {},  # Group by constraint relation counts
        }
        # Accuracy Metrics: Pass@N
        for i in range(args.num_run_per_interaction):
            print_results[f"pass@{i+1}"] = 0
            print_results[f"total_test_cases@{i+1}"] = 0
        
        # Load existing results
        task_simulations = load_existing_results(output_file)
        
        # Create a new list to store updated simulations
        updated_task_simulations = []
        
        # Add a counter for call_database in the main function where evaluations are processed
        total_cases = 0        
        for idx, task_simulation in tqdm(enumerate(task_simulations), desc="Evaluating task simulations"):
            evaluations = []
            user_goal = task_simulation["task"]["user_goal"]
            dependency = task_simulation["task"]["dependency_original"]
            dependency_expanded = task_simulation["task"]["dependency"]
                
            # Count constraints for this task
            num_constraints = count_constraint_units(dependency)
            num_constraints_expanded = count_constraint_units(dependency_expanded)
            # print("Number of constraints in dependency_original:", num_constraints)
            # print("Number of constraints in dependency:", num_constraints_expanded)

            # Initialize goal statistics if not exists
            if user_goal not in print_results["goal_statistics"]:
                print_results["goal_statistics"][user_goal] = {
                    "total_interactions": 0,
                    "total_success": 0,
                    "avg_num_messages": 0,
                    "avg_num_function_calls": 0,
                    "total_tasks": 0,
                    "avg_num_constraints": 0,
                    "avg_num_constraints_expanded": 0,  # New field for expanded constraints per goal
                    "total_constraints": 0,
                    "total_constraints_expanded": 0     # New field to help calculate average
                }
                for i in range(args.num_run_per_interaction):
                    print_results["goal_statistics"][user_goal][f"pass@{i+1}"] = 0
                    print_results["goal_statistics"][user_goal][f"total_test_cases@{i+1}"] = 0
            
            for interaction_log in task_simulation["interactions"]:
                
                results = {"final_database": interaction_log["database"]}
                interaction = interaction_log["interaction"]
                
                # collect the function call and response
                func_calls = []
                for i in range(len(interaction)-1):
                    if interaction[i].get("tool_calls", []):
                        # Clean N/A function call
                        for tool_call in interaction[i]["tool_calls"]:
                            if tool_call["function"]["name"].lower() in ["n/a", "na", "none", "null"]:
                                interaction[i]["tool_calls"].remove(tool_call)
                        if len(interaction[i]["tool_calls"]) > 0:
                            func_calls.append({
                                "tool_name": interaction[i+1]["tool_name"],
                                "arguments": try_eval(interaction[i]["tool_calls"][0]["function"]["arguments"]),
                                "content": try_eval(interaction[i+1]["content"])
                            })
                
                # Use directed graph evaluator instead of gorilla
                evaluation_result = evaluator_function_directed_graph(
                    domain_str=task_simulation["domain"],
                    task=task_simulation["task"],
                    log_msg_fcall=interaction,
                    func_calls=func_calls,
                    results=results,
                    default_constraint_option=args.default_constraint_option)
                evaluations.append(evaluation_result)
                if args.verbose:
                    print(json.dumps(evaluation_result, indent=4))
                
                # Update error statistics
                print_results["error_statistics"]["total_evaluations"] += 1
                
                # Only track errors for failed cases
                if not evaluation_result.get("success", False):
                    print_results["error_statistics"]["total_failures"] += 1
                    # Check all status indicators for each failed evaluation
                    if not evaluation_result["no_tool_call_error"]:
                        print_results["error_statistics"]["error_causes"]["tool_call_errors"] += 1

                    if not evaluation_result["constraint_not_violated"]:
                        print_results["error_statistics"]["error_causes"]["constraint_violations"] += 1

                    if not evaluation_result["database_match"]:
                        print_results["error_statistics"]["error_causes"]["database_mismatches"] += 1

                    if not evaluation_result["dirgraph_satisfied"]:
                        print_results["error_statistics"]["error_causes"]["dirgraph_violations"] += 1

                    if not evaluation_result["action_called_correctly"]:
                        print_results["error_statistics"]["error_causes"]["incorrect_action_calls"] += 1
                
                # Update outcome categories based on specific error combinations
                database_correct = evaluation_result["database_match"]
                procedure_correct = evaluation_result["dirgraph_satisfied"]
                action_correct = evaluation_result["action_called_correctly"]
                
                # Check if there are outcome errors (database_match or action_called_correctly)
                outcome_error = not database_correct or not action_correct
                
                if procedure_correct and not outcome_error:
                    # All three metrics are correct
                    print_results["error_statistics"]["outcome_categories"]["outcome_correct_procedure_correct"] += 1
                elif not procedure_correct and not outcome_error:
                    # Only dirgraph_violations error
                    print_results["error_statistics"]["outcome_categories"]["outcome_correct_procedure_wrong"] += 1
                elif procedure_correct and outcome_error:
                    # No dirgraph_violations BUT (database_mismatches OR incorrect_action_calls)
                    print_results["error_statistics"]["outcome_categories"]["outcome_wrong_procedure_correct"] += 1
                elif not procedure_correct and outcome_error:
                    # Both dirgraph_violations AND (database_mismatches OR incorrect_action_calls)
                    print_results["error_statistics"]["outcome_categories"]["outcome_wrong_procedure_wrong"] += 1
            
            # Increment counters after checking all interactions for this task
            total_cases += 1
            
            # collect the function call and response
            func_calls = []
            for i in range(len(evaluations)-1):
                func_calls.append({
                    "tool_name": evaluations[i+1]["tool_name"],
                    "arguments": evaluations[i]["arguments"],
                    "content": evaluations[i]["content"]
                })

            # Create a new task simulation dict with the evaluations
            updated_simulation = copy.deepcopy(task_simulation)
            updated_simulation["evaluations"] = evaluations
            updated_simulation["statistics"] = task_statistics(evaluations)
            
            # Add to our new list
            updated_task_simulations.append(updated_simulation)
            
            # update the overall statistics and goal-specific statistics
            if updated_simulation["statistics"]["total_interactions"] > 0:
                # record the print results
                print_results["total_tasks"] += 1
                print_results["total_interactions"] += updated_simulation["statistics"]["total_interactions"]
                print_results["total_success"] += updated_simulation["statistics"]["total_success"]
                print_results["avg_num_messages"] += updated_simulation["statistics"]["avg_num_messages"]
                print_results["avg_num_function_calls"] += updated_simulation["statistics"]["avg_num_function_calls"]
                print_results["avg_num_constraints"] += num_constraints
                print_results["avg_num_constraints_expanded"] += num_constraints_expanded  # Add expanded constraints

                # Update goal-specific statistics
                goal_stats = print_results["goal_statistics"][user_goal]
                goal_stats["total_tasks"] += 1
                goal_stats["total_interactions"] += updated_simulation["statistics"]["total_interactions"]
                goal_stats["total_success"] += updated_simulation["statistics"]["total_success"]
                goal_stats["avg_num_messages"] += updated_simulation["statistics"]["avg_num_messages"]
                goal_stats["avg_num_function_calls"] += updated_simulation["statistics"]["avg_num_function_calls"]
                goal_stats["total_constraints"] += num_constraints
                goal_stats["total_constraints_expanded"] += num_constraints_expanded  # Add expanded constraints

                # Pass@N for overall and goal-specific
                for i in range(min(args.num_run_per_interaction, updated_simulation["statistics"]["total_interactions"])):
                    print_results[f"pass@{i+1}"] += int(updated_simulation["statistics"][f"pass@{i+1}"])
                    print_results[f"total_test_cases@{i+1}"] += 1
                    goal_stats[f"pass@{i+1}"] += int(updated_simulation["statistics"][f"pass@{i+1}"])
                    goal_stats[f"total_test_cases@{i+1}"] += 1

            # Group by number of constraints
            constraint_count = num_constraints
            if constraint_count >= args.max_constraints:
                constraint_count = f"{args.max_constraints}+"
            elif constraint_count <= 1:  # Group 0 and 1 together as "1"
                constraint_count = 1
                
            if constraint_count not in print_results["constraint_group_statistics"]:
                print_results["constraint_group_statistics"][constraint_count] = {
                    "total_tasks": 0,
                    "total_interactions": 0,
                    "total_success": 0,
                    "avg_num_messages": 0,
                    "avg_num_function_calls": 0,
                    "pass_rate": 0
                }
            
            group_stats = print_results["constraint_group_statistics"][constraint_count]
            if updated_simulation["statistics"]["total_interactions"] > 0:
                group_stats["total_tasks"] += 1
                group_stats["total_interactions"] += updated_simulation["statistics"]["total_interactions"]
                group_stats["total_success"] += updated_simulation["statistics"]["total_success"]
                group_stats["avg_num_messages"] += updated_simulation["statistics"]["avg_num_messages"]
                group_stats["avg_num_function_calls"] += updated_simulation["statistics"]["avg_num_function_calls"]

            # Count constraint relations and create group key
            num_constraint_relations = count_constraint_relations(dependency)
            relation_group_key = "-".join(["{}:{}".format(r, bool(v)) for r, v in sorted(num_constraint_relations.items()) if v > 0])
            
            # Initialize constraint relation group if not exists
            if relation_group_key not in print_results["constraint_relation_group_statistics"]:
                print_results["constraint_relation_group_statistics"][relation_group_key] = {
                    "total_tasks": 0,
                    "total_interactions": 0,
                    "total_success": 0,
                    "avg_num_messages": 0,
                    "avg_num_function_calls": 0,
                    "pass_rate": 0
                }
            
            # Update constraint relation group statistics
            if updated_simulation["statistics"]["total_interactions"] > 0:
                relation_group_stats = print_results["constraint_relation_group_statistics"][relation_group_key]
                relation_group_stats["total_tasks"] += 1
                relation_group_stats["total_interactions"] += updated_simulation["statistics"]["total_interactions"]
                relation_group_stats["total_success"] += updated_simulation["statistics"]["total_success"]
                relation_group_stats["avg_num_messages"] += updated_simulation["statistics"]["avg_num_messages"]
                relation_group_stats["avg_num_function_calls"] += updated_simulation["statistics"]["avg_num_function_calls"]

        # Save the updated task simulations
        save_results(new_output_file, updated_task_simulations, verbose=True)
        
        if args.domain == "all":
            combined_results[current_domain] = print_results
        
    if args.domain == "all":
        # Create "all" directory
        all_output_dir = f"{args.output_dir}/all"
        os.makedirs(all_output_dir, exist_ok=True)
        
        # Calculate and save aggregate statistics across all domains
        aggregate_results = {
            "user_model": args.user_model,
            "assistant_model": args.assistant_model,
            "domain": "all",
            "domain_specific_results": combined_results,
            "aggregate_statistics": {
                "total_tasks": sum(r["total_tasks"] for r in combined_results.values()),
                "total_interactions": sum(r["total_interactions"] for r in combined_results.values()),
                "total_success": sum(r["total_success"] for r in combined_results.values()),
                "avg_num_messages": sum(r["avg_num_messages"] * r["total_tasks"] for r in combined_results.values()) / 
                                  sum(r["total_tasks"] for r in combined_results.values()),
                "avg_num_function_calls": sum(r["avg_num_function_calls"] * r["total_tasks"] for r in combined_results.values()) / 
                                        sum(r["total_tasks"] for r in combined_results.values()),
                "avg_num_constraints": sum(r["avg_num_constraints"] * r["total_tasks"] for r in combined_results.values()) / 
                                     sum(r["total_tasks"] for r in combined_results.values()),
                "avg_num_constraints_expanded": sum(r["avg_num_constraints_expanded"] * r["total_tasks"] for r in combined_results.values()) / 
                                              sum(r["total_tasks"] for r in combined_results.values())
            },
            "error_statistics": {             
                "total_evaluations": sum(r["error_statistics"]["total_evaluations"] for r in combined_results.values()),
                "total_failures": sum(r["error_statistics"]["total_failures"] for r in combined_results.values()),
                "error_causes": {
                    "tool_call_errors": sum(r["error_statistics"]["error_causes"]["tool_call_errors"] for r in combined_results.values()),
                    "constraint_violations": sum(r["error_statistics"]["error_causes"]["constraint_violations"] for r in combined_results.values()),
                    "database_mismatches": sum(r["error_statistics"]["error_causes"]["database_mismatches"] for r in combined_results.values()),
                    "dirgraph_violations": sum(r["error_statistics"]["error_causes"]["dirgraph_violations"] for r in combined_results.values()),
                    "incorrect_action_calls": sum(r["error_statistics"]["error_causes"]["incorrect_action_calls"] for r in combined_results.values())
                },
                "outcome_categories": {
                    "outcome_correct_procedure_wrong": sum(r["error_statistics"]["outcome_categories"]["outcome_correct_procedure_wrong"] for r in combined_results.values()),
                    "outcome_wrong_procedure_wrong": sum(r["error_statistics"]["outcome_categories"]["outcome_wrong_procedure_wrong"] for r in combined_results.values()),
                    "outcome_wrong_procedure_correct": sum(r["error_statistics"]["outcome_categories"]["outcome_wrong_procedure_correct"] for r in combined_results.values()),
                    "outcome_correct_procedure_correct": sum(r["error_statistics"]["outcome_categories"]["outcome_correct_procedure_correct"] for r in combined_results.values())
                }
            }
        }

        # Aggregate constraint group statistics across all domains
        all_constraint_groups = {}
        
        for domain_results in combined_results.values():
            # Existing constraint count aggregation
            for constraint_count, stats in domain_results["constraint_group_statistics"].items():
                if constraint_count not in all_constraint_groups:
                    all_constraint_groups[constraint_count] = {
                        "total_tasks": 0,
                        "total_interactions": 0,
                        "total_success": 0,
                        "avg_num_messages": 0,
                        "avg_num_function_calls": 0,
                    }
                group = all_constraint_groups[constraint_count]
                group["total_tasks"] += stats["total_tasks"]
                group["total_interactions"] += stats["total_interactions"]
                group["total_success"] += stats["total_success"]
                group["avg_num_messages"] += stats["avg_num_messages"] * stats["total_tasks"]
                group["avg_num_function_calls"] += stats["avg_num_function_calls"] * stats["total_tasks"]
            
            # Pass@N for overall and goal-specific
            for i in range(args.num_run_per_interaction):
                if f"pass@{i+1}" in domain_results:  # Check if the pass@N metric exists
                    for goal, goal_stats in domain_results["goal_statistics"].items():
                        if f"pass@{i+1}" in goal_stats:  # Check if the goal has this metric
                            goal_stats[f"pass@{i+1}"] += domain_results[f"pass@{i+1}"]
                            goal_stats[f"total_test_cases@{i+1}"] += 1

        # Calculate averages for aggregated constraint groups
        for constraint_count, stats in all_constraint_groups.items():
            if stats["total_tasks"] > 0:
                stats["avg_num_messages"] /= stats["total_tasks"]
                stats["avg_num_function_calls"] /= stats["total_tasks"]
                stats["pass_rate"] = stats["total_success"] / stats["total_interactions"] if stats["total_interactions"] > 0 else 0

        # Sort constraint groups using the already defined sort key function
        aggregate_results["aggregate_constraint_groups"] = dict(sorted(
            all_constraint_groups.items(),
            key=lambda x: constraint_group_sort_key(x, args.max_constraints)
        ))

        # Calculate aggregate pass rates
        total_interactions = sum(r["total_interactions"] for r in combined_results.values())
        aggregate_results["aggregate_statistics"]["pass_rate"] = (
            sum(r["total_success"] for r in combined_results.values()) / total_interactions if total_interactions > 0 else 0
        )
        
        # Calculate error percentages based on total evaluations for all domains
        total_evaluations = aggregate_results["error_statistics"]["total_evaluations"]
        if total_evaluations > 0:
            error_percentages = {}
            for error, count in aggregate_results["error_statistics"]["error_causes"].items():
                error_percentages[f"{error}_percentage"] = (count / total_evaluations) * 100
            aggregate_results["error_statistics"]["percentages"] = error_percentages

            # Add outcome category percentages for aggregated results
            outcome_percentages = {}
            for outcome, count in aggregate_results["error_statistics"]["outcome_categories"].items():
                outcome_percentages[f"{outcome}_percentage"] = (count / total_evaluations) * 100
            aggregate_results["error_statistics"]["outcome_percentages"] = outcome_percentages
        
        # Aggregate constraint relation group statistics across all domains
        all_relation_groups = {}
        
        for domain_results in combined_results.values():
            for relation_group, stats in domain_results["constraint_relation_group_statistics"].items():
                if relation_group not in all_relation_groups:
                    all_relation_groups[relation_group] = {
                        "total_tasks": 0,
                        "total_interactions": 0,
                        "total_success": 0,
                        "avg_num_messages": 0,
                        "avg_num_function_calls": 0,
                    }
                group = all_relation_groups[relation_group]
                group["total_tasks"] += stats["total_tasks"]
                group["total_interactions"] += stats["total_interactions"]
                group["total_success"] += stats["total_success"]
                group["avg_num_messages"] += stats["avg_num_messages"] * stats["total_tasks"]
                group["avg_num_function_calls"] += stats["avg_num_function_calls"] * stats["total_tasks"]
        
        # Calculate averages for aggregated relation groups
        for stats in all_relation_groups.values():
            if stats["total_tasks"] > 0:
                stats["avg_num_messages"] /= stats["total_tasks"]
                stats["avg_num_function_calls"] /= stats["total_tasks"]
                stats["pass_rate"] = stats["total_success"] / stats["total_interactions"] if stats["total_interactions"] > 0 else 0
        
        # Sort relation groups by total tasks
        aggregate_results["aggregate_relation_groups"] = dict(sorted(
            all_relation_groups.items(),
            key=lambda x: x[1]["total_tasks"],
            reverse=True
        ))

        # Save aggregate results in the "all" directory
        aggregate_output_file = os.path.join(
            all_output_dir,
            (f"usr_{args.user_model.replace('/', '_')}-" if args.user_model else "") + \
            f"ast_{args.assistant_model.replace('/', '_')}-" + \
            f"mode_{args.tool_call_mode}-" + \
            f"dep_{args.default_constraint_option}-" + \
            f"fmt_{args.constraint_descr_format}-" + \
            f"tool_{args.tool_list}-" + \
            f"shuffle_{args.shuffle_func}.json"
        )
        
        with open(aggregate_output_file, 'w') as f:
            json.dump(aggregate_results, f, indent=4)
        
        # Print the aggregate results
        print(json.dumps(aggregate_results, indent=4))
    else:
        # Calculate overall statistics         
        print_results["pass_rate"] = print_results["total_success"] / print_results["total_interactions"]
        print_results["avg_num_messages"] /= print_results["total_tasks"]
        print_results["avg_num_function_calls"] /= print_results["total_tasks"]
        print_results["avg_num_constraints"] /= print_results["total_tasks"]
        print_results["avg_num_constraints_expanded"] /= print_results["total_tasks"]
        
        # calculate pass rate
        for i in range(args.num_run_per_interaction):
            if print_results[f"total_test_cases@{i+1}"] > 0:
                print_results[f"pass@{i+1}"] /= print_results[f"total_test_cases@{i+1}"]
            else:
                del print_results[f"pass@{i+1}"]
            del print_results[f"total_test_cases@{i+1}"]

        # Calculate goal-specific statistics
        for goal, stats in print_results["goal_statistics"].items():
            if stats["total_interactions"] > 0:
                stats["pass_rate"] = stats["total_success"] / stats["total_interactions"]
                stats["avg_num_messages"] /= stats["total_tasks"]
                stats["avg_num_function_calls"] /= stats["total_tasks"]
                stats["avg_num_constraints"] = stats["total_constraints"] / stats["total_tasks"]
                stats["avg_num_constraints_expanded"] = stats["total_constraints_expanded"] / stats["total_tasks"]
                del stats["total_constraints"]
                del stats["total_constraints_expanded"]
                
                # Calculate pass@N for each goal
                for i in range(args.num_run_per_interaction):
                    if stats[f"total_test_cases@{i+1}"] > 0:
                        stats[f"pass@{i+1}"] /= stats[f"total_test_cases@{i+1}"]
                    else:
                        del stats[f"pass@{i+1}"]
                    del stats[f"total_test_cases@{i+1}"]

        # Sort goal_statistics by avg_num_constraints
        sorted_goals = dict(sorted(
            print_results["goal_statistics"].items(),
            key=lambda x: x[1]["avg_num_constraints"]
        ))
        print_results["goal_statistics"] = sorted_goals

        # Calculate averages for constraint groups
        for constraint_count, stats in print_results["constraint_group_statistics"].items():
            if stats["total_tasks"] > 0:
                stats["avg_num_messages"] /= stats["total_tasks"]
                stats["avg_num_function_calls"] /= stats["total_tasks"]
                stats["pass_rate"] = stats["total_success"] / stats["total_interactions"]

        # Sort constraint_group_statistics using the already defined sort key function
        sorted_constraint_groups = dict(sorted(
            print_results["constraint_group_statistics"].items(),
            key=lambda x: constraint_group_sort_key(x, args.max_constraints)
        ))
        print_results["constraint_group_statistics"] = sorted_constraint_groups

        # Calculate error percentages based on total evaluations
        total_evaluations = print_results["error_statistics"]["total_evaluations"]
        if total_evaluations > 0:
            error_percentages = {}
            for error, count in print_results["error_statistics"]["error_causes"].items():
                error_percentages[f"{error}_percentage"] = (count / total_evaluations) * 100
            print_results["error_statistics"]["percentages"] = error_percentages

            # Add outcome category percentages
            outcome_percentages = {}
            for outcome, count in print_results["error_statistics"]["outcome_categories"].items():
                outcome_percentages[f"{outcome}_percentage"] = (count / total_evaluations) * 100
            print_results["error_statistics"]["outcome_percentages"] = outcome_percentages

        # Calculate averages for constraint relation groups
        for stats in print_results["constraint_relation_group_statistics"].values():
            if stats["total_tasks"] > 0:
                stats["avg_num_messages"] /= stats["total_tasks"]
                stats["avg_num_function_calls"] /= stats["total_tasks"]
                stats["pass_rate"] = stats["total_success"] / stats["total_interactions"] if stats["total_interactions"] > 0 else 0
        
        # Sort constraint relation groups by total tasks
        print_results["constraint_relation_group_statistics"] = dict(sorted(
            print_results["constraint_relation_group_statistics"].items(),
            key=lambda x: x[1]["total_tasks"],
            reverse=True
        ))

        # Print the results
        print(json.dumps(print_results, indent=4))

def count_constraint_units(dependency):
    """
    Count the number of constraint units in a dependency structure.
    A constraint unit is a 'single' condition that represents a basic constraint.
    
    Args:
        dependency: A nested list representing the dependency structure
        
    Returns:
        int: Number of constraint units found
    """
    if not dependency:
        return 0
    
    # If it's a single constraint
    if isinstance(dependency, list) and len(dependency) >= 1 and dependency[0] == "single":
        return 1
    
    # If it's a logical operator (and/or)
    if isinstance(dependency, list) and len(dependency) >= 2 and dependency[0] in ["and", "or"]:
        count = 0
        # Recursively count constraints in each branch
        for branch in dependency[1]:
            count += count_constraint_units(branch)
        return count
    return 0

def count_constraint_relations(dependency):
    """
    Count occurrences of relation types in a dependency structure.
    Handles different dependency formats including:
    - Lists and nested lists
    - Strings
    - Dictionaries
    - None values
    
    Relations counted:
    - "single"
    - "and"
    - "or"
    - "chain"
    
    Args:
        dependency: A dependency structure that could be a list, nested list, string, dict, or None
        
    Returns:
        dict: Number of constraint relations found
    """
    relations = {"single": 0, "and": 0, "or": 0, "chain": 0}
    
    # Handle None or empty cases
    if dependency is None or (isinstance(dependency, (list, dict)) and not dependency):
        return relations
    
    # Handle string case
    if isinstance(dependency, str):
        return relations
    
    # Handle dictionary case
    if isinstance(dependency, dict):
        # Recursively process all values in the dictionary
        for value in dependency.values():
            sub_relations = count_constraint_relations(value)
            for key in relations:
                relations[key] += sub_relations[key]
        return relations
    
    # Handle list case
    if isinstance(dependency, list):
        # Empty list
        if not dependency:
            return relations
            
        # Get the relation type (first element)
        relation_type = dependency[0] if isinstance(dependency[0], str) else None
        
        # Count the relation if it's one we're tracking
        if relation_type in relations:
            relations[relation_type] += 1
        
        # Process remaining elements based on relation type
        if len(dependency) > 1:
            if relation_type in ["and", "or"]:
                # For 'and' and 'or', expect a list of branches as second element
                if isinstance(dependency[1], list):
                    for branch in dependency[1]:
                        sub_relations = count_constraint_relations(branch)
                        for key in relations:
                            relations[key] += sub_relations[key]
            elif relation_type in ["single", "chain"]:
                # For 'single' and 'chain', process the second element
                sub_relations = count_constraint_relations(dependency[1])
                for key in relations:
                    relations[key] += sub_relations[key]
            else:
                # If relation_type not recognized, process all elements
                for element in dependency[1:]:
                    sub_relations = count_constraint_relations(element)
                    for key in relations:
                        relations[key] += sub_relations[key]
    
    return relations

def task_statistics(evaluations):
    """Calculate statistics for a task's evaluations."""
    if not evaluations:
        return {
            "total_interactions": 0,
            "total_success": 0,
            "avg_num_messages": 0,
            "avg_num_function_calls": 0
        }
    
    # Count constraint units for the first evaluation
    # (assuming all evaluations in the same task have the same dependency structure)
    num_constraints = 0
    if evaluations and "dependency" in evaluations[0]:
        num_constraints = count_constraint_units(evaluations[0]["dependency"])
        
    stats = {
        "total_interactions": len(evaluations),
        "total_success": sum(1 for e in evaluations if e["success"]),
        "avg_num_messages": sum(e["num_messages"] for e in evaluations) / len(evaluations),
        "avg_num_function_calls": sum(e["num_function_calls"] for e in evaluations) / len(evaluations),
        "num_constraints": num_constraints  # Add the constraint count to statistics
    }
    
    # Calculate Pass@N statistics
    for i in range(len(evaluations)):
        # Check if any evaluation up to index i was successful
        stats[f"pass@{i+1}"] = any(e["success"] for e in evaluations[:i+1])
    
    return stats

if __name__ == "__main__":
    main()